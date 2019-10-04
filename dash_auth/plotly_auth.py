from __future__ import absolute_import

import base64
import datetime
import os
import time
import warnings

import flask
import json
import requests

from hmac import compare_digest
from six import iteritems

import dash_html_components as html
import dash_core_components as dcc
from dash.dependencies import Output, Input

from .oauth import OAuthBase, need_request_context

from . import api_requests


deprecation_notice = '''
PlotlyAuth is deprecated.
If your app is still using Dash Deployment Server < 3.0,
you can still use this package.

The repo will be broken down into 2 different repos:

dash-basic-auth -> basic http auth for dash apps.
dash-enterprise-auth -> Dash Deployment Server integration, replace PlotlyAuth.
'''


class PlotlyAuth(OAuthBase):
    AUTH_COOKIE_NAME = 'plotly_auth'
    TOKEN_COOKIE_NAME = 'plotly_oauth_token'

    def __init__(self, app, app_name, sharing, app_url,
                 authorization_hook=None):
        """
        Provides Plotly Authentication login screen to a Dash app.

        Args:
            app: A `dash.Dash` app
            app_name: The name of your Dash app. This name will be registered
                on the Plotly server
            sharing: 'private', 'public', or 'secret'
            app_url: String or list of strings. The URL(s) of the Dash app.
                This is used to register your app with Plotly's OAuth system.
                For example, to test locally, supply a list of URLs with
                the first URL being your remote server and the second URL
                being e.g. http://localhost:8050
        Returns:
            None
        """
        self._logout_url = os.getenv('DASH_LOGOUT_URL')
        warnings.warn(deprecation_notice, PendingDeprecationWarning)
        super(PlotlyAuth, self).__init__(
            app,
            app_url,
            secret_key=api_requests.credential('plotly_api_key'),
            salt=app_name,
            authorization_hook=authorization_hook,
            add_routes=not self._logout_url,
        )

        if not self._logout_url:
            self._dash_app = create_or_overwrite_dash_app(
                app_name, sharing, app_url
            )
            oauth_app = create_or_overwrite_oauth_app(
                app_url, app_name
            )
            self._oauth_client_id = oauth_app['client_id']
            self._sharing = sharing

    def html(self, script):
        return ('''
            <!doctype html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>Log In</title>
            </head>
            <body>
              <div id="react-entry-point"></div>
            </body>
            <script id="_auth-config" type="application/json">
            {}
            </script>
            <script type="text/javascript">{}</script>
            </html>
        '''.format(
            json.dumps({
                'oauth_client_id': self._oauth_client_id,
                'plotly_domain': api_requests.config('plotly_domain'),
                'requests_pathname_prefix':
                    self._app.config['requests_pathname_prefix']
            }),
            script)
        )

    def login_api(self):
        oauth_token = flask.request.get_json()['access_token']
        res = api_requests.get(
            '/v2/users/current?kerberos=1',
            headers={'Authorization': 'Bearer {}'.format(oauth_token)},
        )
        try:
            res.raise_for_status()
        except Exception as e:
            print(res.content)
            raise e

        data = res.json()
        response = flask.Response(
            json.dumps(data),
            mimetype='application/json',
            status=res.status_code
        )

        self.set_user_name(data.get('username'))

        hooks = []
        for hook in self._auth_hooks:
            hooks.append(hook(data))

        if not all(hooks):
            @flask.after_this_request
            def _rep(rep):
                self.clear_cookies(rep)
                return rep

        self.set_cookie(
            response=response,
            name='plotly_oauth_token',
            value=oauth_token,
            max_age=None
        )

        return response

    def is_authorized(self):
        if self._sharing == 'secret':
            share_key = flask.request.args.get('share_key')
            app_share_key = self._dash_app['share_key']

            if share_key and compare_digest(str(share_key),
                                            str(app_share_key)):
                return True

            if self.access_token_is_valid():
                return True

        return super(PlotlyAuth, self).is_authorized()

    def index_auth_wrapper(self, original_index):
        def wrap(*args, **kwargs):
            if self.is_authorized():
                response = original_index(*args, **kwargs)
                return self.add_access_token_to_response(response)
            else:
                return self.login_request()
        return wrap

    def check_view_access(self, oauth_token):
        return check_view_access(oauth_token, self._dash_app['fid'])

    @need_request_context
    def get_kerberos_ticket_cache(self):
        token = flask.request.cookies.get('plotly_oauth_token')

        res = api_requests.get(
            '/v2/users/current?kerberos=1',
            headers={'Authorization': 'Bearer {}'.format(token)},
        )
        res_json = res.json()

        expiry_str = res_json['kerberos_ticket_expiry']
        expiry = datetime.datetime.strptime(expiry_str, '%Y-%m-%dT%H:%M:%SZ')
        if expiry < datetime.datetime.utcnow():
            raise Exception('Kerberos ticket has expired.')

        return base64.b64decode(res_json['kerberos_ticket_cache'])

    def logout(self):
        token = flask.request.cookies.get('plotly_oauth_token')
        data = {
            'token': token,
            'client_id': self._oauth_client_id,
        }

        @flask.after_this_request
        def _after(rep):
            self.clear_cookies(rep)
            return rep

        streambed_ip = os.environ.get('DASH_STREAMBED_DIRECT_IP')
        try:
            invalidation_resp = requests.post(
                '{}{}'.format('https://{}'.format(streambed_ip)
                              if streambed_ip
                              else api_requests.config('plotly_domain'),
                              '/Auth/o/revoke_token/'),
                verify=False if streambed_ip else True,
                data=data)
            invalidation_resp.raise_for_status()
        except requests.HTTPError as e:
            print('Invalidation failure {}'.format(repr(e)))

    def create_logout_button(self,
                             id='logout-btn',
                             redirect_to='',
                             label='Logout',
                             **button_props):
        if self._logout_url:
            return dcc.LogoutButton(
                id=id,
                label=label,
                logout_url=self._logout_url,
                **button_props
            )

        location_id = '{}-{}'.format(id, 'loc')

        btn = html.Div([
            html.Button(label, id=id, **button_props),
            dcc.Location(id=location_id),
        ])

        # setup the callback only after the btn has been inserted in the layout
        @self.app.server.before_first_request
        def _log_out_callback():

            @self.app.callback(Output(location_id, 'href'),
                               [Input(id, 'n_clicks')])
            def _on_log_out(n_clicks):
                if not n_clicks:
                    return

                app_url = self._app_url[0] if \
                    isinstance(self._app_url, (list, tuple)) else self._app_url

                redirect = redirect_to or '{}?t={}'.format(
                    app_url,
                    int(time.time()))

                self.logout()

                return redirect

        return btn

    def get_username(self, validate_max_age=True, response=None):
        if self._logout_url:
            user_data = json.loads(
                    flask.request.headers.get('Plotly-User-Data', "{}")
                    )
            return user_data.get('username')
        else:
            return super(PlotlyAuth, self).get_username(
                validate_max_age, response)


def create_or_overwrite_dash_app(filename, sharing, app_url):
    required_args = {
        'filename': filename,
        'sharing': sharing,
        'app_url': app_url
    }
    for arg_name, arg_value in iteritems(required_args):
        if arg_value is None:
            raise Exception('{} is required'.format(arg_name))
    if sharing not in ['private', 'public', 'secret']:
        raise Exception(
            "The privacy argument must be equal "
            "to 'private', 'public', or 'secret'.\n"
            "You supplied '{}'".format(sharing)
        )
    payload = json.dumps({
        'filename': filename,
        'share_key_enabled': True if sharing == 'secret' else False,
        'world_readable': True if sharing == 'public' else False,
        'app_url': app_url if isinstance(app_url, str) else app_url[0]
    })

    res_lookup = api_requests.get('/v2/files/lookup?path={}'.format(filename))
    if res_lookup.status_code == 404:
        res_create = api_requests.post('/v2/dash-apps', data=payload)
        try:
            res_create.raise_for_status()
        except Exception as e:
            print(payload)
            print(res_create.content)
            raise e
        app = res_create.json()['file']
        return app
    elif res_lookup.status_code == 200:
        app = res_lookup.json()
        fid = app['fid']
        res_update = api_requests.patch(
            '/v2/dash-apps/{}'.format(fid),
            data=payload
        )
        try:
            res_update.raise_for_status()
        except Exception as e:
            print(payload)
            print(res_update.content)
            raise e
        return app
    else:
        print(res_lookup.content)
        res_lookup.raise_for_status()


def create_or_overwrite_oauth_app(app_url, name):
    if isinstance(app_url, str):
        redirect_uris = '{}/_oauth-redirect'.format(app_url.strip('/'))
    else:
        redirect_uris = ' '.join([
            '{}/_oauth-redirect'.format(url.strip('/'))
            for url in app_url
        ])

    request_data = {
        'data': json.dumps({
            'name': name,
            'client_type': 'public',
            'authorization_grant_type': 'implicit',
            'redirect_uris': redirect_uris,
        })
    }

    res = api_requests.post('/v2/oauth-apps/update_or_create', **request_data)

    if res.status_code != 405:
        try:
            res.raise_for_status()
        except Exception as e:
            print(res.content)
            raise e

        return res.json()

    # The update_or_create endpoint does not exist; fall back to the old
    # behaviour (which is racy and may result in 2 applications being created)
    res = api_requests.get(
        '/v2/oauth-apps/lookup',
        params={'name': name},
    )
    try:
        res.raise_for_status()
    except Exception as e:
        print(res.content)
        raise e
    apps = res.json()
    if apps:
        oauth_app_id = apps[0]['id']
        res = api_requests.patch(
            '/v2/oauth-apps/{}'.format(oauth_app_id),
            **request_data
        )
    else:
        res = api_requests.post('/v2/oauth-apps', **request_data)

    try:
        res.raise_for_status()
    except Exception as e:
        print(res.content)
        raise e

    return res.json()


def check_view_access(oauth_token, fid):
    res = api_requests.get(
        '/v2/files/{}'.format(fid),
        headers={'Authorization': 'Bearer {}'.format(oauth_token)}
    )
    if res.status_code == 200:
        return True
    elif res.status_code == 404:
        return False
    else:
        # TODO - Dash exception
        raise Exception('Failed request to plotly')

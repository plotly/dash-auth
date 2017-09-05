from __future__ import absolute_import
import datetime
import flask
from flask_seasurf import SeaSurf
import json
import os
from six import iteritems
from .auth import Auth

from . import api_requests

AUTH_COOKIE_NAME = 'plotly_auth'


class PlotlyAuth(Auth):
    def __init__(self, app, app_name, sharing, app_url):
        Auth.__init__(self, app)

        self.config = {
            'permissions_cache_expiry': 5 * 60
        }

        self._fid = create_or_overwrite_dash_app(
            app_name, sharing, app_url
        )
        self._oauth_client_id = create_or_overwrite_oauth_app(
            app_url, app_name
        )['client_id']

        self._app = app
        self._app_url = app_url
        self._sharing = sharing
        self._access_codes = self.create_access_codes()

        app.server.add_url_rule(
            '{}_dash-login'.format(app.url_base_pathname),
            view_func=login_api,
            methods=['post']
        )

        app.server.add_url_rule(
            '{}_oauth-redirect'.format(app.url_base_pathname),
            view_func=self.serve_oauth_redirect,
            methods=['get']
        )

        app.server.add_url_rule(
            '{}_is-authorized'.format(app.url_base_pathname),
            view_func=self.check_if_authorized,
            methods=['get']
        )
        _current_path = os.path.dirname(os.path.abspath(__file__))

        # TODO - Dist files
        self.oauth_redirect_bundle = open(os.path.join(
            _current_path, 'oauth-redirect.js')).read()
        self.login_bundle = open(
            os.path.join(_current_path, 'login.js')).read()

    def create_access_codes(self):
        token = SeaSurf()._generate_token()
        new_access_codes = {
            'access_granted': token,
            'expiration': (
                datetime.datetime.now() + datetime.timedelta(
                    seconds=self.config['permissions_cache_expiry']
                )
            )
        }
        self._access_codes = new_access_codes
        return self._access_codes

    def is_authorized(self):
        if 'plotly_oauth_token' not in flask.request.cookies:
            return False

        oauth_token = flask.request.cookies['plotly_oauth_token']

        if (datetime.datetime.now() > self._access_codes['expiration']):
            self.create_access_codes()

        if AUTH_COOKIE_NAME not in flask.request.cookies:
            return check_view_access(oauth_token, self._fid)

        access_cookie = flask.request.cookies[AUTH_COOKIE_NAME]

        # If there access was previously declined,
        # check access again in case it has changed
        if access_cookie != self._access_codes['access_granted']:
            return check_view_access(oauth_token, self._fid)

        return True

    def check_if_authorized(self):
        if self.is_authorized():
            return flask.Response(status=200)

        return flask.Response(status=403)


    def auth_wrapper(self, f):
        def wrap(*args, **kwargs):
            if not self.is_authorized():
                return flask.Response(status=403)

            response = f(*args, **kwargs)
            # TODO - should set secure in this cookie, not exposed in flask
            # TODO - should set path or domain
            response.set_cookie(
                AUTH_COOKIE_NAME,
                value=self._access_codes['access_granted'],
                max_age=(60 * 60 * 24 * 7),  # 1 week
            )
            return response
        return wrap

    def html(self, script):
        return ('''
            <!doctype html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>Log In</title>
            </head>
            <body>
              <div id="react-root"></div>
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
                'requests_pathname_prefix': self._app.config.requests_pathname_prefix
            }),
            script)
        )

    def login_request(self):
        return self.html(self.login_bundle)

    def serve_oauth_redirect(self):
        return self.html(self.oauth_redirect_bundle)


def login_api():
    oauth_token = flask.request.get_json()['access_token']
    res = api_requests.get(
        '/v2/users/current',
        headers={'Authorization': 'Bearer {}'.format(oauth_token)},
    )
    try:
        res.raise_for_status()
    except Exception as e:
        print(res.content)
        raise e
    response = flask.Response(
        json.dumps(res.json()),
        mimetype='application/json',
        status=res.status_code
    )
    # TODO - set path and secure appropriately
    response.set_cookie(
        'plotly_oauth_token',
        value=oauth_token,
        max_age=None
    )

    return response


def create_or_overwrite_dash_app(filename, sharing, app_url):
    required_args = {
        'filename': filename,
        'sharing': sharing,
        'app_url': app_url
    }
    for arg_name, arg_value in iteritems(required_args):
        if arg_value is None:
            raise Exception('{} is required'.format(arg_name))
    if sharing not in ['private', 'public']:
        raise Exception(
            "The privacy argument must be equal "
            "to 'private' or 'public'.\n"
            "You supplied '{}'".format(sharing)
        )
    payload = json.dumps({
        'filename': filename,
        'share_key_enabled': True if sharing == 'secret' else False,
        'world_readable': True if sharing == 'public' else False,
        'app_url': app_url
    })

    res_lookup = api_requests.get('/v2/files/lookup?path={}'.format(filename))
    if res_lookup.status_code == 404:
        # TODO - Better request handling
        res_create = api_requests.post('/v2/dash-apps', data=payload)
        try:
            res_create.raise_for_status()
        except Exception as e:
            print(payload)
            print(res_create.content)
            raise e
        fid = res_create.json()['file']['fid']
        return fid
    elif res_lookup.status_code == 200:
        fid = res_lookup.json()['fid']
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
        return fid
    else:
        print(res_lookup.content)
        res_lookup.raise_for_status()



def create_or_overwrite_oauth_app(app_url, name):
    redirect_uris = [
        '{}/_oauth-redirect'.format(i) for i in [
            # TODO - variable or app.server.settings port
            'http://localhost:8050',
            'http://127.0.0.1:8050',
            app_url
        ]
    ]
    request_data = {
        'data': json.dumps({
            'name': name,
            'client_type': 'public',
            'authorization_grant_type': 'implicit',
            'redirect_uris': ' '.join(redirect_uris),
        })
    }

    # Check if app already exists.
    # If it does, then update it.
    # If it doesn't, then create a new one.
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
    if len(apps) > 1:
        raise Exception(
            'There are more than one oauth apps with the name {}.'.format(name)
        )
    elif len(apps) == 1:
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

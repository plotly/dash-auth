import datetime
import flask
from flask_seasurf import SeaSurf
import json
import os
import plotly
import requests
from six import iteritems

from auth import Auth


AUTH_COOKIE_NAME = 'plotly_auth'

class PlotlyAuth(Auth):
    def __init__(self, app, app_name, sharing, app_url):
        Auth.__init__(self, app)

        self.fid = create_or_overwrite_dash_app(
            app_name, sharing, app_url
        )
        self.oauth_client_id = create_or_overwrite_oauth_app(
            app_url, app_name
        )['client_id']

        self.app_url = app_url
        self.sharing = sharing
        self.access_codes = self.create_access_codes()
        self.plotly_domain = 'https://plot.ly'

        app.server.add_url_rule(
            '{}_dash-login'.format(app.url_base_pathname),
            view_func=self.login_api,
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
        self.oauth_redirect_bundle = open(os.path.join(_current_path, 'oauth-redirect.js')).read()
        self.login_bundle = open(os.path.join(_current_path, 'login.js')).read()


    class config:
        permissions_cache_expiry = 5 * 60

    def create_access_codes(self):
        token = SeaSurf()._generate_token()
        new_access_codes = {
            'access_granted': token,
            'expiration': (
                datetime.datetime.now() + datetime.timedelta(
                    seconds=self.config.permissions_cache_expiry
                )
            )
        }
        self.access_codes = new_access_codes
        return self.access_codes

    def is_authorized(self):
        if 'plotly_oauth_token' not in flask.request.cookies:
            return False

        oauth_token = flask.request.cookies['plotly_oauth_token']

        if (datetime.datetime.now() > self.access_codes['expiration']):
            create_access_codes()

        if AUTH_COOKIE_NAME not in flask.request.cookies:
            return check_view_access(oauth_token, self.fid)
        else:
            access_cookie = flask.request.cookies[AUTH_COOKIE_NAME]

            # If there access was previously declined,
            # check access again in case it has changed
            if access_cookie != self.access_codes['access_granted']:
                return check_view_access(oauth_token, self.fid)
            else:
                return True

    def check_if_authorized(self):
        if self.is_authorized():
            return flask.Response(status=200)
        else:
            return flask.Response(status=403)

    def auth_wrapper(self, f):
        def wrap(*args, **kwargs):
            if not self.is_authorized():
                return flask.Response(status=403)
            else:
                response = f(*args, **kwargs)
                # TODO - should set secure in this cookie, not exposed in flask
                # TODO - should set path or domain
                response.set_cookie(
                    AUTH_COOKIE_NAME,
                    value=self.access_codes['access_granted'],
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
                'oauth_client_id': self.oauth_client_id,
                'plotly_domain': self.plotly_domain
            }),
            script)
        )

    def login_html(self):
        return self.html(self.login_bundle)

    def login_api(self):
        oauth_token = flask.request.get_json()['access_token']
        print('login_api')
        print(oauth_token)
        res = requests.get(
            '{}/v2/users/current'.format(
                plotly.config.get_config()['plotly_api_domain']
            ),
            headers={
                'Authorization': 'Bearer {}'.format(oauth_token)
            }
        )
        res.raise_for_status()
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

    def serve_oauth_redirect(self):
        return self.html(self.oauth_redirect_bundle)


def create_or_overwrite_dash_app(filename, sharing, app_url):
    required_args = {
        'filename': filename,
        'sharing': sharing,
        'app_url': app_url
    }
    for arg_name, arg_value in iteritems(required_args):
        if arg_value is None:
            raise Exception('{} is required'.format(arg_name))
    if sharing not in ['private', 'secret', 'public']:
        raise Exception(
            "The privacy argument must be equal "
            "to 'private', 'public', or 'secret'.\n"
            "You supplied '{}'".format(sharing)
        )
    payload = {
        'filename': filename,
        'share_key_enabled': True if sharing == 'secret' else False,
        'world_readable': True if sharing == 'public' else False,
        'app_url': app_url
    }

    try:
        # TODO - Handle folders
        res = plotly.api.v2.files.lookup(filename)
    except Exception as e:
        print(e)
        # TODO - How to check if it is a
        # plotly.exceptions.PlotlyRequestException?
        res_create = plotly.api.v2.dash_apps.create(payload)
        fid = res_create.json()['file']['fid']
    else:
        fid = res.json()['fid']
        # TODO - Does plotly.api call `raise_for_status`?
        res = plotly.api.v2.dash_apps.update(fid, payload)
        res.raise_for_status()
    return fid

def create_or_overwrite_oauth_app(app_url, name):

    redirect_uris = [
        '{}/_oauth-redirect'.format(i) for i in [
            # TODO - windows does localhost?
            # TODO - variable port?
            'http://localhost:8050',
            app_url
        ]
    ]

    creds = plotly.tools.get_credentials_file()

    # TODO - Use lookup
    res = requests.post(
        'https://api.plot.ly/v2/oauth-apps',
        auth=(creds['username'], creds['api_key'],),
        headers={'plotly-client-platform': 'python'},
        data={
            'name': name,
            'client_type': 'public',
            'authorization_grant_type': 'implicit',
            'redirect_uris': ' '.join(redirect_uris),
        }
    )

    res.raise_for_status()

    return res.json()

def check_view_access(oauth_token, fid):
    res = requests.get(
        '{}/v2/files/{}'.format(
            plotly.config.get_config()['plotly_api_domain'],
            fid
        ),
        headers={
            'Authorization': 'Bearer {}'.format(oauth_token)
        }
    )
    if res.status_code == 200:
        return True
    elif res.status_code == 404:
        return False
    else:
        # TODO - Dash exception
        raise Exception('Failed request to plotly')

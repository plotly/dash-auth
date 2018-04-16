from __future__ import absolute_import
import flask
import json
import os
from textwrap import dedent
import itsdangerous

from .auth import Auth


class OAuthBase(Auth):
    # Name of the cookie containing the cached permission token
    AUTH_COOKIE_NAME = 'dash_token'
    # Name of the cookie containing the OAuth2 access token
    TOKEN_COOKIE_NAME = 'oauth_token'

    def __init__(
            self,
            app,
            app_url,
            client_id=None,
            secret_key=None,
            salt=None):
        Auth.__init__(self, app)

        self.config = {
            'permissions_cache_expiry': 5 * 60
        }

        self._app = app
        self._app_url = app_url
        self._oauth_client_id = client_id

        if secret_key is None and app.server.secret_key is None:
            raise Exception(dedent('''
                app.server.secret_key is missing.
                Generate a secret key in your Python session
                with the following commands:

                >>> import os
                >>> import base64
                >>> base64.b64encode(os.urandom(30)).decode('utf-8')

                and assign it to the property app.server.secret_key
                (where app is your dash app instance).
                Note that you should not do this dynamically:
                you should create a key and then assign the value of
                that key in your code.
            '''))

        if salt is None:
            raise Exception(dedent('''
                salt is missing. The salt parameter needs to a string that
                is unique to this individual Dash app.
            '''))

        self._signer = itsdangerous.TimestampSigner(secret_key, salt=salt)

        app.server.add_url_rule(
            '{}_dash-login'.format(app.config['routes_pathname_prefix']),
            view_func=self.login_api,
            methods=['post']
        )

        app.server.add_url_rule(
            '{}_oauth-redirect'.format(app.config['routes_pathname_prefix']),
            view_func=self.serve_oauth_redirect,
            methods=['get']
        )

        app.server.add_url_rule(
            '{}_is-authorized'.format(app.config['routes_pathname_prefix']),
            view_func=self.check_if_authorized,
            methods=['get']
        )
        _current_path = os.path.dirname(os.path.abspath(__file__))

        # TODO - Dist files
        with open(os.path.join(_current_path, 'oauth-redirect.js'), 'r') as f:
            self.oauth_redirect_bundle = f.read()

        with open(os.path.join(_current_path, 'login.js'), 'r') as f:
            self.login_bundle = f.read()

    def access_token_is_valid(self):
        if self.AUTH_COOKIE_NAME not in flask.request.cookies:
            return False

        access_token = flask.request.cookies[self.AUTH_COOKIE_NAME]

        try:
            self._signer.unsign(
                access_token,
                max_age=self.config['permissions_cache_expiry']
            )
            return True
        except itsdangerous.SignatureExpired:
            # Check access in case the user is valid but the token has expired
            return False
        except itsdangerous.BadSignature:
            # Access tokens in previous versions of `dash-auth`
            # weren't generated with itsdangerous
            # and will raise `BadSignature`
            return False

    def is_authorized(self):
        if self.TOKEN_COOKIE_NAME not in flask.request.cookies:
            return False

        oauth_token = flask.request.cookies[self.TOKEN_COOKIE_NAME]
        if not self.access_token_is_valid():
            return self.check_view_access(oauth_token)

        return True

    def check_if_authorized(self):
        if self.is_authorized():
            return flask.Response(status=200)

        return flask.Response(status=403)

    def add_access_token_to_response(self, response):
        """
        Add an access token cookie to a response if it doesn't
        already have a valid one. (To be called if auth succeeds to make
        auth "sticky" for other requests.)

        :param (flask.Response|str|unicode) response
        :rtype: (flask.Response)
        """
        try:
            # Python 2
            if isinstance(response, basestring):  # noqa: F821
                response = flask.Response(response)
        except Exception:
            # Python 3
            if isinstance(response, str):
                response = flask.Response(response)

        if not self.access_token_is_valid():
            access_token = self._signer.sign('access')
            self.set_cookie(
                response,
                name=self.AUTH_COOKIE_NAME,
                value=access_token,
                max_age=(60 * 60 * 24 * 7),  # 1 week
            )

        return response

    def auth_wrapper(self, f):
        def wrap(*args, **kwargs):
            if not self.is_authorized():
                return flask.Response(status=403)

            try:
                response = f(*args, **kwargs)
            except Exception as err:
                # Clear the cookie if auth fail
                if getattr(err, 'status_code', None) in [401, 403]:
                    response = flask.Response(status=403)
                    self.clear_cookies(response)
                    return response
                else:
                    raise

            # TODO - should set secure in this cookie, not exposed in flask
            # TODO - should set path or domain
            return self.add_access_token_to_response(response)
        return wrap

    def index_auth_wrapper(self, original_index):
        def wrap(*args, **kwargs):
            if self.is_authorized():
                return original_index(*args, **kwargs)
            else:
                return self.login_request()
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
                'requests_pathname_prefix':
                    self._app.config['requests_pathname_prefix']
            }),
            script)
        )

    def login_request(self):
        return self.html(self.login_bundle)

    def serve_oauth_redirect(self):
        return self.html(self.oauth_redirect_bundle)

    def set_cookie(self, response, name, value, max_age):
        response.set_cookie(
            name,
            value=value,
            max_age=max_age,
            secure=True if 'https:' in self._app_url else False,
            path=self._app.config['routes_pathname_prefix']
        )

    def clear_cookies(self, response):
        response.set_cookie(
            self.TOKEN_COOKIE_NAME,
            value='',
            expires=0,
            secure=True if 'https:' in self._app_url else False
        )
        response.set_cookie(
            self.AUTH_COOKIE_NAME,
            value='',
            expires=0,
            secure=True if 'https:' in self._app_url else False
        )

    def check_view_access(self, oauth_token):
        """Checks the validity of oauth_token."""
        raise NotImplementedError()

    def login_api(self):
        """Obtains the access_token from the URL, sets the cookie."""
        oauth_token = flask.request.get_json()['access_token']

        response = flask.Response(
            '{}',
            mimetype='application/json',
            status=200
        )

        self.set_cookie(
            response=response,
            name=self.TOKEN_COOKIE_NAME,
            value=oauth_token,
            max_age=None
        )

        return response

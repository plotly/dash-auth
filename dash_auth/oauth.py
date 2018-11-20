from __future__ import absolute_import
import flask
import json
import os
from textwrap import dedent
import itsdangerous
import functools

from ua_parser import user_agent_parser

from .auth import Auth


def need_request_context(func):
    @functools.wraps(func)
    def _wrap(*args, **kwargs):
        if not flask.has_request_context():
            raise RuntimeError('`{0}` method needs a flask/dash request'
                               ' context to run. Make sure to run '
                               '`{0}` from a callback.'.format(func.__name__))
        return func(*args, **kwargs)
    return _wrap


class OAuthBase(Auth):
    # Name of the cookie containing the cached permission token
    AUTH_COOKIE_NAME = 'dash_token'
    # Name of the cookie containing the OAuth2 access token
    TOKEN_COOKIE_NAME = 'oauth_token'
    USERNAME_COOKIE = 'dash_user'
    USERDATA_COOKIE = 'dash_user_data'

    def __init__(
            self,
            app,
            app_url,
            client_id=None,
            secret_key=None,
            salt=None, authorization_hook=None,
            add_routes=True):
        Auth.__init__(self, app, authorization_hook,
                      _overwrite_index=add_routes)

        self.config = {
            'permissions_cache_expiry': 5 * 60,
            'user_cookies_expiry': 604800,  # one week.
        }

        self._app = app
        self._app_url = app_url
        self._oauth_client_id = client_id
        self._username_cache = {}

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
        self._json_signer = itsdangerous.JSONWebSignatureSerializer(
            secret_key, salt=salt)

        if add_routes:

            app.server.add_url_rule(
                '{}_dash-login'.format(app.config['routes_pathname_prefix']),
                view_func=self.login_api,
                methods=['post']
            )

            app.server.add_url_rule(
                '{}_oauth-redirect'.format(
                    app.config['routes_pathname_prefix']),
                view_func=self.serve_oauth_redirect,
                methods=['get']
            )

            app.server.add_url_rule(
                '{}_is-authorized'.format(
                    app.config['routes_pathname_prefix']),
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
            # noinspection PyUnresolvedReferences
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

            username = self.get_username(
                validate_max_age=False, response=response)
            userdata = self.get_user_data(response=response)

            if username:
                self.set_user_name(username, response)
            if userdata:
                self.set_user_data(userdata, response)

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

    def set_cookie(self, response, name, value, max_age,
                   httponly=True, samesite='Strict'):

        secure = True if 'https:' in self._app_url else False

        is_http = flask.request.environ.get(
            'wsgi.url_scheme',
            flask.request.environ.get('HTTP_X_FORWARDED_PROTO', 'http')
        ) == 'http'

        ua = user_agent_parser.ParseUserAgent(
            flask.request.environ.get('HTTP_USER_AGENT', ''))

        if ua.get('family') == 'Electron' and is_http:
            secure = False

        response.set_cookie(
            name,
            value=value,
            max_age=max_age,
            secure=secure,
            path=self._app.config['requests_pathname_prefix'].rstrip('/'),
            httponly=httponly,
            samesite=samesite
        )

    def clear_cookies(self, response):
        """
        Clear all the auth cookies.

        :param response:
        :type response: flask.Response
        :return:
        """
        for c in (
                self.AUTH_COOKIE_NAME,
                self.TOKEN_COOKIE_NAME,
                self.USERDATA_COOKIE,
                self.USERNAME_COOKIE):
            self._clear_cookie(response, c)

    def _clear_cookie(self, response, cookie_name):
        response.set_cookie(cookie_name,
                            value='',
                            expires=0,
                            path=self._app.config['requests_pathname_prefix']
                            .rstrip('/'),
                            secure='https:' in self._app_url)

    def _unsign(self, s, max_age=None, is_json=False, response=None):
        try:
            if is_json:
                return self._json_signer.loads(s)
            return self._signer.unsign(s, max_age=max_age)
        except itsdangerous.BadSignature:
            if response:
                self.clear_cookies(response)
            else:
                @flask.after_this_request
                def _clear(rep):
                    self.clear_cookies(rep)

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

    @need_request_context
    def get_username(self, validate_max_age=True, response=None):
        """
        Retrieve the username from the `dash_user` cookie.

        :return: The stored username if any.
        :rtype: str
        """
        cached = self._username_cache.get(flask.request.remote_addr)
        if cached:
            return cached
        username = flask.request.cookies.get(self.USERNAME_COOKIE)
        if username:
            max_age = None
            if validate_max_age:
                max_age = self.config['permissions_cache_expiry']
            unsigned = self._unsign(username,
                                    max_age=max_age, response=response)
            return unsigned.decode('utf-8')

    @need_request_context
    def get_user_data(self, response=None):
        """
        Retrieve the user data from `dash_user_data` cookie.

        :return: The stored user data if any.
        :rtype: dict
        """

        user_data = flask.request.cookies.get(self.USERDATA_COOKIE)
        if user_data:
            signed = self._unsign(user_data, is_json=True, response=response)
            return signed

    @need_request_context
    def set_user_name(self, name, response=None):
        """
        Store the username in the `dash_user` cookie.

        :param name: the name of the user.
        :type name: str
        :param response:
        :type response: flask.Response
        :return:
        """
        self._username_cache[flask.request.remote_addr] = name

        if not response:
            @flask.after_this_request
            def _set_username(rep):
                self.set_cookie(
                    rep,
                    self.USERNAME_COOKIE,
                    self._signer.sign(name),
                    max_age=self.config['user_cookies_expiry'])
                del self._username_cache[flask.request.remote_addr]
                return rep
        else:
            self.set_cookie(
                response, self.USERNAME_COOKIE, self._signer.sign(name),
                max_age=self.config['user_cookies_expiry'])

    @need_request_context
    def set_user_data(self, data, response=None):
        """
        Set meta data for a user to store in a cookie.

        :param data: Data to encode and store.
        :type data: dict, list
        :param response:
        :type response: flask.Response
        :return:
        """

        if not response:
            @flask.after_this_request
            def _set_data(rep):
                self.set_cookie(
                    rep,
                    self.USERDATA_COOKIE,
                    self._json_signer.dumps(data),
                    max_age=self.config['user_cookies_expiry'])
                return rep
        else:
            self.set_cookie(
                response,
                self.USERDATA_COOKIE,
                self._json_signer.dumps(data),
                max_age=self.config['user_cookies_expiry'])

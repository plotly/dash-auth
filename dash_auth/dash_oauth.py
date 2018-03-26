from __future__ import absolute_import
import datetime
import flask
from flask_seasurf import SeaSurf
import json
import os
from textwrap import dedent
import itsdangerous
from itsdangerous import TimestampSigner

from .auth import Auth


class DashTokenAuth(Auth):
    # Name of the cookie containing the cached permission token
    AUTH_COOKIE_NAME = 'dash_token'
    # Name of the cookie containing the OAuth2 access token
    TOKEN_COOKIE_NAME = 'user_token'

    def __init__(self, app, client_id=None):
        Auth.__init__(self, app)

        self.config = {
            'permissions_cache_expiry': 30
        }

        self._app = app
        # self._app_url = app_url
        self._oauth_client_id = client_id

        if (app.server.secret_key is None or
                app.server.secret_key in ['secret-key', 'secret', '']):
            raise Exception(dedent('''
                Missing or invalid secret_key. Set a secret key on
                app.server.secret_key

                Generate a secret key with:
                >>> import os
                >>> os.urandom(30)
            '''))
        self._signer = TimestampSigner(app.server.secret_key)
        app.server.add_url_rule(
            '{}auth/login'.format(app.config['routes_pathname_prefix']),
            view_func=self.login,
            methods=['post']
        )
        app.server.add_url_rule(
            '{}auth/logout'.format(app.config['routes_pathname_prefix']),
            view_func=self.logout
        )

    def is_authorized(self):
        if (self.TOKEN_COOKIE_NAME not in flask.request.cookies or
                self.AUTH_COOKIE_NAME not in flask.request.cookies):
            return False

        token = flask.request.cookies[self.TOKEN_COOKIE_NAME]
        access = flask.request.cookies[self.AUTH_COOKIE_NAME]
        has_access = self.is_access_code_valid(access)
        if has_access:
            return True
        else:
            # access has expired - check access again
            return self.validate_token(token)

    def is_access_code_valid(self, token):
        try:
            self._signer.unsign(
                token,
                max_age=self.config['permissions_cache_expiry'])
            print('Token is valid')
            return True
        except itsdangerous.SignatureExpired as e:
            print(e)
            return False

    def check_if_authorized(self):
        if self.is_authorized():
            return flask.Response(status=200)

        return flask.Response(status=403)

    def auth_wrapper(self, f):
        def wrap(*args, **kwargs):
            if not self.is_authorized():
                return flask.Response(status=403)

            response = f(*args, **kwargs)
            try:
                # Python 2
                if isinstance(response, basestring):  # noqa: F821
                    response = flask.Response(response)
            except:
                # Python 3
                if isinstance(response, str):
                    response = flask.Response(response)

            # they have access but they're time-expiring access
            # token may have expired. if so, grant them a new one
            if not self.is_access_code_valid(
                    flask.request.cookies[self.AUTH_COOKIE_NAME]):
                self.set_auth_cookie(response)

            return response
        return wrap

    def logout(self):
        response = self.login_request()
        response.set_cookie(
            self.TOKEN_COOKIE_NAME,
            value='',
            expires=0,
        )
        response.set_cookie(
            self.AUTH_COOKIE_NAME,
            value='',
            expires=0,
        )
        return response


    def set_auth_cookie(self, response):
        response.set_cookie(
            self.AUTH_COOKIE_NAME,
            value=self._signer.sign('access'),
            # TODO - secure and path 
        )

    def login(self):
        username = flask.request.form['username']
        password = flask.request.form['password']

        (has_access, token) = self.validate_user(username, password)
        if has_access:
            # TODO - Config for the other app name
            response = flask.redirect('/')

            self.set_auth_cookie(response)
            response.set_cookie(
                self.TOKEN_COOKIE_NAME,
                value=token,
                # TODO - configurable path
            )
            return response
        else:
            return flask.redirect(
                '{}auth/login'.format(
                    self.app.config['routes_pathname_prefix']
                )
            )


    def validate_user(self, username, password):
        """Checks the validity of user.
        Returns a tuple of (has_access, token)
        """
        raise NotImplementedError()

    def validate_token(self, user_token):
        """Checks the validity of user_token.
        Returns a boolean
        """
        raise NotImplementedError()

    def login_request(self):
        return flask.redirect(
            '{}auth/login'.format(self.app.config['routes_pathname_prefix']))

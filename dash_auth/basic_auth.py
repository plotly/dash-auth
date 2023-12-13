import base64
from typing import Union, Callable
import flask
from dash import Dash

from .auth import Auth


class BasicAuth(Auth):
    def __init__(
        self,
        app: Dash,
        username_password_list: Union[list, dict],
        auth_func: Callable = None
    ):
        """Add basic authentication to Dash.

        :param app: Dash app
        :param username_password_list: username:password list, either as a
            list of tuples or a dict
        :param auth_func: python function accepting two arguments (username, password) 
            and returning a tuple (username, password) which is checked against 
            username_password_list.
        """
        Auth.__init__(self, app)
        self._users = (
            username_password_list
            if isinstance(username_password_list, dict)
            else {k: v for k, v in username_password_list}
        )
        self._auth_func = auth_func

    def is_authorized(self):
        header = flask.request.headers.get('Authorization', None)
        if not header:
            return False
        username_password = base64.b64decode(header.split('Basic ')[1])
        username_password_utf8 = username_password.decode('utf-8')
        username, password = username_password_utf8.split(':', 1)
        if self._auth_func is not None:
            try:
                username, password = self._auth_func(username, password)
            except:
                pass
        return self._users.get(username) == password

    def login_request(self):
        return flask.Response(
            'Login Required',
            headers={'WWW-Authenticate': 'Basic realm="User Visible Realm"'},
            status=401
        )

    def auth_wrapper(self, f):
        def wrap(*args, **kwargs):
            if not self.is_authorized():
                return flask.Response(status=403)

            response = f(*args, **kwargs)
            return response
        return wrap

    def index_auth_wrapper(self, original_index):
        def wrap(*args, **kwargs):
            if self.is_authorized():
                return original_index(*args, **kwargs)
            else:
                return self.login_request()
        return wrap

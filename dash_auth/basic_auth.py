from .auth import Auth
import base64
import flask


class BasicAuth(Auth):
    def __init__(self, app, username_password_list):
        Auth.__init__(self, app)
        self._username_password_list = username_password_list

    def is_authorized(self):
        header = flask.request.headers.get('Authorization', None)
        if not header:
            return False
        username_password = base64.b64decode(header.split('Basic ')[1])
        username_password_utf8 = username_password.decode('utf-8')
        username, password = username_password_utf8.split(':')
        for pair in self._username_password_list:
            if pair[0] == username and pair[1] == password:
                return True

        return False

    def login_request(self):
        return flask.Response(
            'Login Required',
            headers={'WWW-Authenticate': 'Basic realm="User Visible Realm"'},
            status=401)

    def auth_wrapper(self, f):
        def wrap(*args, **kwargs):
            if not self.is_authorized():
                return flask.Response(status=403)

            response = f(*args, **kwargs)
            return response
        return wrap

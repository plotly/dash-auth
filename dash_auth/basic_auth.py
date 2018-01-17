from .auth import Auth
import base64
import flask
import hashlib


class BasicAuth(Auth):

    VALID_HASH_TYPES = [
        'sha1','sha224','sha256','sha384','sha512','blake2b','blake2s',
        'md5','sha3_224','sha3_256','sha3_512','shake_128','shake_256'
    ]

    def __init__(self, app, username_password_list, hash_type=None):
        Auth.__init__(self, app)
        self._username_password_list = username_password_list
        self._hash_type = hash_type

    def is_authorized(self):
        header = flask.request.headers.get('Authorization', None)
        if not header:
            return False
        username_password = base64.b64decode(header.split('Basic ')[1])
        username_password_utf8 = username_password.decode('utf-8')
        username, password = username_password_utf8.split(':')
        if self._hash_type in VALID_HASH_TYPES:
            username = hashlib.new(self._hash_type, username.encode()).hexdigest()
            password = hashlib.new(self._hash_type, password.encode()).hexdigest()
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
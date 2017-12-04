import unittest
import os
from flask import Flask
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State
from dash import Dash
from dash_auth import FlaskLoginAuth
import sqlite3
import hashlib
from flask_login import UserMixin
import pprint

class FlaskLoginAuthTest(unittest.TestCase):
    # Test FlaskLoginAuth functionality

    def setUp(self):
        """Set up for tests.  Need to provid Flask.test_client() to all tests.  Further
        configuration (e.g. FlaskLoginAuth) must be provided within the tests."""
        server = Flask(__name__)
        server.config.update(
            SECRET_KEY = os.urandom(12),
        )

        self.app = Dash(name='app1', url_base_pathname='/app1', server=server)
        self.app.layout = html.Div('Hello World!')

        self.add_auth_app = Dash(name='add_auth_app', url_base_pathname='/add-auth-app', server=server)
        self.add_auth_app.layout = html.Div('Hello World!')

        self.multi_app_no_auth = Dash(name='multi_app_no_auth', url_base_pathname='/app-no-auth', server=server)
        self.multi_app_no_auth.layout = html.Div('Hello World!')

        # Will raise an error because it doesn't have the same server
        self.crash_app = Dash(name='crash', url_base_pathname='/crash-app')
        self.crash_app.layout = html.Div('Goodby Cruel World!')

        self.server = server.test_client()
        self.assertEqual(server.debug, False)

    def tearDown(self):
        pass

    def custom_hash(self, string):

        return string + '123'

    def login_user(self, username, password):
        self.server.post('/login', data=dict(username=username, password=password))

    def login_logout(self, username, password):
        response = self.server.get('/login',)
        self.assertEqual(response.status_code, 200)

        # Check that pages are protected before logging in
        response = self.server.get('/logout',)
        self.assertEqual(response.status_code, 302, 'Not logged in yet, server should redirect.')

        response = self.server.get('/app1',)
        self.assertEqual(response.status_code, 302, 'Not logged in yet, server should redirect.')

        self.login_user(username, password)

        response = self.server.get('/app1',)
        self.assertEqual(response.status_code, 200, 'Logged in, should be 200 Okay')

        response = self.server.get('/logout',)
        self.assertEqual(response.status_code, 200, 'Logged in, should be 200 Okay')

        # Check that logout has worked
        response = self.server.get('/app1',)
        self.assertEqual(response.status_code, 302, 'If logged out successfully, server should redirect.')

    def test_app_no_auth(self):
        response = self.server.get('/app1', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue('<title>Dash</title>' in response.data)

    def test_app_default_login_no_users(self):

        auth = FlaskLoginAuth(self.app, use_default_views=True)

        self.login_logout('admin', 'admin')

    def test_app_default_login_no_users_no_hash(self):
        # Same as no_users no_hash no_hash_function

        auth = FlaskLoginAuth(self.app, use_default_views=True, auto_hash=False)

        self.login_logout('admin', 'admin')

    def test_app_default_login_no_users_no_hash_custom_hash_func(self):

        auth = FlaskLoginAuth(self.app, use_default_views=True, auto_hash=False, hash_function=self.custom_hash)

        self.login_logout('admin', 'admin')

    def test_app_default_login_no_users_with_autohash_and_custom_hashfunc(self):

        auth = FlaskLoginAuth(self.app, use_default_views=True, auto_hash=True, hash_function=self.custom_hash)

        self.login_logout('admin', 'admin')

    def test_app_default_login_no_users_with_autohash_and_no_custom_hashfunc(self):

        auth = FlaskLoginAuth(self.app, use_default_views=True, auto_hash=True, hash_function=self.custom_hash)

        self.login_logout('admin', 'admin')

    def test_app_default_login_users_obj_list_no_hash_with_custom_hash_func(self):

        users = [User('Steve'), User('sally')]

        # If a hash_function is passed and auth_hash is False, it is assumed that the passed no_hash_function
        # was used to hash the passwords previously, so we need to hash them ahead of time.
        users[0].password=self.custom_hash(users[0].password)
        users[1].password=self.custom_hash(users[1].password)

        auth = FlaskLoginAuth(self.app, use_default_views=True, users=users, auto_hash=False, hash_function=self.custom_hash)

        self.login_logout('sally', 'password')

    def test_app_default_login_users_obj_list_no_hash_no_custom_hash_func(self):

        users = [User('Steve'), User('sally')]

        auth = FlaskLoginAuth(self.app, use_default_views=True, users=users, auto_hash=False, hash_function=None)

        self.login_logout('sally', 'password')

    def test_app_default_login_users_obj_list_with_auto_hash_no_custom_hash_func(self):

        users = [User('Steve'), User('sally')]

        auth = FlaskLoginAuth(self.app, use_default_views=True, users=users, auto_hash=True, hash_function=None)

        self.login_logout('sally', 'password')

    def test_app_default_login_users_obj_list_with_auto_hash_with_custom_hash_func(self):

        users = [User('Steve'), User('sally')]

        auth = FlaskLoginAuth(self.app, use_default_views=True, users=users, auto_hash=True, hash_function=self.custom_hash)

        self.login_logout('sally', 'password')

    def test_multi_wrong_server_exception(self):

        auth = FlaskLoginAuth(self.app, use_default_views=True, auto_hash=True, hash_function=self.custom_hash)

        with self.assertRaises(Exception) as exception:
            auth.add_app(self.crash_app)

        self.login_logout('admin', 'admin')

    def test_multi_app_no_auth_second_app(self):

        auth = FlaskLoginAuth(self.app, use_default_views=True)

        response = self.server.get('/app-no-auth')
        self.assertEqual(response.status_code, 200)

    def test_multi_app_second_app_with_auth(self):

        auth = FlaskLoginAuth(self.app, use_default_views=True)
        auth.add_app(self.add_auth_app)

        # Not logged in yet
        response = self.server.get('/add-auth-app')
        self.assertEqual(response.status_code, 302)

        # Does not require login
        response = self.server.get('/app-no-auth')
        self.assertEqual(response.status_code, 200)

        self.login_user('admin','admin')

        # Logged in
        response = self.server.get('/add-auth-app')
        self.assertEqual(response.status_code, 200)


class User(UserMixin):

    def __init__(self, id):
        self.id = id.lower()
        self.password = 'password'

if __name__ == "__main__":
    unittest.main()

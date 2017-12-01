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

        self.login_user('admin', 'admin')

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

        auth = FlaskLoginAuth(self.app, use_default_views=True, auto_hash=False)

        self.login_logout('admin', 'admin')

    def test_app_default_login_no_users_no_hash_custom_hash_func(self):

        auth = FlaskLoginAuth(self.app, use_default_views=True, auto_hash=False, hash_function=self.custom_hash)

        self.login_logout('admin', self.custom_hash('admin'))

if __name__ == "__main__":
    unittest.main()

from __future__ import absolute_import

import dash
from dash.dependencies import Input, Output
import dash_auth
import dash_core_components as dcc
import dash_html_components as html

import datetime
import flask
from flask import redirect
from flask_seasurf import SeaSurf
import json
import os

import dash_auth


class DashAuthWrapper(dash_auth.auth.Auth):
    # Name of the cookie containing the cached permission token
    AUTH_COOKIE_NAME = 'dash_token'

    def __init__(self, app):
        dash_auth.auth.Auth.__init__(self, app)

        self.config = {
            'permissions_cache_expiry': 5 * 60
        }

        self._app = app
        self._access_codes = self.create_access_codes()

        app.server.add_url_rule(
            '{}auth/login'.format(app.config['routes_pathname_prefix']),
            view_func=self.login,
            methods=['post']
        )
        _current_path = os.path.dirname(os.path.abspath(__file__))

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

    def auth_wrapper(self, f):
        def wrap(*args, **kwargs):
            if not self.is_authorized():
                return flask.redirect('{}auth/login'.format(
                    self._app.config['routes_pathname_prefix']),)

            return f(*args, **kwargs)

        return wrap

    def login(self):
        print('login')
        print(flask.request.form)
        username = flask.request.form['username']
        password = flask.request.form['password']

        if self.validate_user(username, password):
            response = flask.redirect('/')

            response.set_cookie(
                self.AUTH_COOKIE_NAME,
                value=self._access_codes['access_granted'],
                max_age=(60 * 60 * 24 * 7),  # 1 week
            )
            return response
        else:
            return flask.Response(status=403)

    def logout(self):
        # TODO - Clear cookies and redirect?
        response.set_cookie(
            self.AUTH_COOKIE_NAME,
            value='',
            expires=0,
            secure=False
        )

    def is_authorized(self):
        if self.AUTH_COOKIE_NAME not in flask.request.cookies:
            return False
        elif (flask.request.cookies[self.AUTH_COOKIE_NAME] !=
                self._access_codes['access_granted']):
            return False
        else:
            return True

    def validate_user(self, username, password):
        raise NotImplementedError()


    def login_request(self):
        return redirect('/auth/login')

server = flask.Flask(__name__)


class DashAuth(DashAuthWrapper):
    def __init__(self, app):
        DashAuthWrapper.__init__(self, app)

    def validate_user(self, username, password):
        print('validate_user')
        return password == 'password'


main_app = dash.Dash(server=server)
DashAuth(main_app)
auth_app = dash.Dash(server=server, url_base_pathname='/auth/')
auth_app.css.append_css({
    'external_url': 'https://codepen.io/chriddyp/pen/dZVMbK.css'})
auth_app.config['suppress_callback_exceptions']=True

main_app.layout = html.Div([
    html.A('Log out', href='/auth/logout'),
    html.Div('Hello World')
])

auth_app.layout = html.Div([
    html.Div(id='content'),
    dcc.Location(id='url')
])


@auth_app.callback(Output('content', 'children'),
                   [Input('url', 'pathname')])
def update_auth_app(pathname):
    if pathname is None:
        return ''
    elif '/login' in pathname or '/logout' in pathname:
        return html.Form(method='POST', action='/auth/login', children=[
            html.Label([
                'Username',
                dcc.Input(name='username')
            ]),
            html.Label([
                'Password',
                dcc.Input(name='password', type='password', id='password'),
            ]),
            html.Button('Log In', id='submit'),
            html.Div(id='status')
        ])


@auth_app.callback(Output('status', 'children'),
                   [Input('password', 'value')])
def update_status(password):
    if password != 'password':
        return 'Wrong password'
    else:
        return ''


if __name__ == '__main__':
    server.run(debug=True)

import dash
from dash.dependencies import Input, Output, State
import dash_core_components as dcc
import dash_html_components as html

import binascii
import json
import flask
import os

from dash_auth.dash_oauth import DashTokenAuth


server = flask.Flask(__name__)
server.secret_key = (
    'fd8e7047cd8c3bedef10568f124aad5102899537a5ec49e15af1d195caf4'
)
USERS = [
    {
        'username': 'chris',
        'password': 'snowstorm',
        'secret-token': binascii.hexlify(os.urandom(24)),
        'has-access': True
    },
    {
        'username': 'tom',
        'password': 'rainfall',
        'secret-token': binascii.hexlify(os.urandom(24)),
        'has-access': False
    }
]

class DashAuth(DashTokenAuth):
    def __init__(self, app):
        DashTokenAuth.__init__(self, app)

    def validate_user(self, username, password):
        print('validate_user')
        user = [u for u in USERS if u['username'] == username]
        if len(user) == 0:
            return (False, '',)
        else:
            if user[0]['password'] == password and user[0]['has-access']:
                return (True, user[0]['secret-token'],)
            else:
                return (False, '',)

    def validate_token(self, user_token):
        print('validate_token')
        user = [u for u in USERS if u['secret-token'] == user_token]
        if len(user) == 0:
            return False
        else:
            return user[0]['has-access']


main_app = dash.Dash(server=server)
DashAuth(main_app)
auth_app = dash.Dash(server=server, url_base_pathname='/auth/')
auth_app.css.append_css({
    'external_url': 'https://codepen.io/chriddyp/pen/dZVMbK.css'})
auth_app.config['suppress_callback_exceptions'] = True

main_app.layout = html.Div([
    html.A('Log out', href='/auth/logout'),
    html.Div('Hello World')
])

auth_app.layout = html.Div([
    html.Div(id='content'),
    dcc.Location(id='url')
])

login_form = html.Form(method='POST', action='/auth/login', children=[
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

@auth_app.callback(Output('content', 'children'),
                   [Input('url', 'pathname')])
def update_auth_app(pathname):
    if pathname is None:
        return ''
    elif '/login' in pathname:
        return login_form
    elif '/logout' in pathname:
        return html.Div([
            html.Div('You are logged out'),
            login_form
        ])


if __name__ == '__main__':
    server.run(debug=True)

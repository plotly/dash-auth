# -*- coding: utf-8 -*-
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

class User(UserMixin):

    def __init__(self, id):
        self.id = id.lower()
        self.password = 'password'

def hash_str(string):
    hasher = hashlib.md5()
    hasher.update(string.encode('utf-8'))
    hashed = hasher.hexdigest()

    return hashed

def hasher(string):
    return string

# Setup the Flask server
server = Flask(__name__)

# config
server.config.update(
    SECRET_KEY = os.urandom(12),
)

# Create our initial Dash App
app = Dash(name='app1', url_base_pathname='/app1', server=server)

conn = sqlite3.connect('H:\\documents\\dashboards\\cataract_dash - flask-login-test\\data\\app_data.db')

#auth = FlaskLoginAuth(app, use_default_views=True, users=conn, auto_hash=False, hash_function=hash_str)

users = [User('Steve'), User('sally')]

auth = FlaskLoginAuth(app, use_default_views=True, users=users, auto_hash=True, hash_function=hasher)

app.layout = html.Div(children=[
    html.H1(children='Hello Dash'),

    html.Div(children='''
        Dash: A web application framework for Python.
    '''),

    dcc.Graph(
        id='example-graph',
        figure={
            'data': [
                {'x': [1, 2, 3], 'y': [4, 1, 2], 'type': 'bar', 'name': 'SF'},
                {'x': [1, 2, 3], 'y': [2, 4, 5], 'type': 'bar', 'name': u'Montréal'},
            ],
            'layout': {
                'title': 'Dash Data Visualization'
            }
        }
    ),
    html.A(dcc.Input(value='Log Out', type='submit'), href='/logout', )
])

app.css.append_css({
    'external_url': 'https://codepen.io/chriddyp/pen/bWLwgP.css',
})

# Run the server
if __name__ == '__main__':
    server.run(debug=True, port=8050)

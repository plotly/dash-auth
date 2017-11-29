import os
from flask import Flask
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State
from dash import Dash
from dash_auth import FlaskLoginAuth

# Setup the Flask server
server = Flask(__name__)

# config
server.config.update(
    SECRET_KEY = os.urandom(12),
)

# Create our initial Dash App
app = Dash(name='app1', url_base_pathname='/app1', server=server)

users = [('steve', 'password'), ('sally', 'password')]

auth = FlaskLoginAuth(app, use_default_views=True, users=users)

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

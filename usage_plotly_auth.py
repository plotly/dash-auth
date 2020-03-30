import dash
from dash.dependencies import Input, Output
import dash_auth
import dash_html_components as html
import dash_core_components as dcc
import os


# Set your http://plotly.com username and api key in the environ or here.
os.environ.setdefault('PLOTLY_USERNAME', '<insert username>')
os.environ.setdefault('PLOTLY_API_KEY', '<insert_api_key>')

external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
app = dash.Dash('auth', external_stylesheets=external_stylesheets)
auth = dash_auth.PlotlyAuth(
    app,
    'Dash Authentication Sample App',
    'private',
    'http://localhost:8050'
)
server = app.server


app.layout = html.Div([
    html.H1('Welcome to the app'),
    html.H3('You are successfully authorized'),
    dcc.Dropdown(
        id='dropdown',
        options=[{'label': i, 'value': i} for i in ['A', 'B']],
        value='A'
    ),
    dcc.Graph(id='graph')
], className="container")


@app.callback(Output('graph', 'figure'), [Input('dropdown', 'value')])
def update_graph(dropdown_value):
    return {
        'layout': {
            'title': 'Graph of {}'.format(dropdown_value),
            'margin': {
                'l': 20,
                'b': 20,
                'r': 10,
                't': 60
            }
        },
        'data': [{'x': [1, 2, 3], 'y': [4, 1, 2]}]
    }


if __name__ == '__main__':
    app.run_server(debug=True)

from dash import Dash, Input, Output, dcc, html
import dash_auth

# Keep this out of source code repository - save in a file or a database
VALID_USERNAME_PASSWORD_PAIRS = {
    'hello': 'world'
}


# Authorization function defined by developer
# (can be used instead of VALID_USERNAME_PASSWORD_PAIRS [Example 2 below])
def authorization_function(username, password):
    if (username == "hello") and (password == "world"):
        return True
    else:
        return False


external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
app = Dash(__name__, external_stylesheets=external_stylesheets)

# Example 1 (using username/password map)
auth = dash_auth.BasicAuth(app, VALID_USERNAME_PASSWORD_PAIRS)

# Example 2 (using authorization function)
# auth = dash_auth.BasicAuth(app, auth_func=authorization_function)

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

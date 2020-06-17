from dash.dependencies import Input, Output
import dash
import dash_html_components as html
import dash_core_components as dcc
import requests
import bcrypt


from .IntegrationTests import IntegrationTests
from dash_auth import basic_auth


def hash_password(passwd):
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(passwd.encode('utf8'), salt)

TEST_USERS_PLAINTEXT = {
    'valid': [
        ['hello', 'world'],
        ['hello2', 'wo:rld']
    ],
    'invalid': [
        ['hello', 'password']
    ],
}

TEST_USERS_HASHED = {
    'valid': [
        ['hello', hash_password('world')],
        ['hello2', hash_password('wo:rld')]
    ],
    'invalid': [
        ['hello', hash_password('password')]
    ],
}


class Tests(IntegrationTests):
    def test_basic_auth_login_flow(self):
        app = dash.Dash(__name__)
        app.layout = html.Div([
            dcc.Input(
                id='input',
                value='initial value'
            ),
            html.Div(id='output')
        ])

        @app.callback(Output('output', 'children'), [Input('input', 'value')])
        def update_output(new_value):
            return new_value

        basic_auth.BasicAuth(
            app,
            TEST_USERS_HASHED['valid']
        )

        self.startServer(app, skip_visit=True)

        self.assertEqual(
            requests.get('http://localhost:8050').status_code,
            401
        )

        # Test login for each user:
        for user, password in TEST_USERS_PLAINTEXT['valid']:
            # login using the URL instead of the alert popup
            # selenium has no way of accessing the alert popup
            self.driver.get(
                'http://{user}:{password}@localhost:8050'.format(
                    user=user,
                    password=password))

            # the username:password@host url doesn't work right now for dash
            # routes, but it saves the credentials as part of the browser.
            # visiting the page again will use the saved credentials
            self.driver.get('http://localhost:8050')
            self.wait_for_text_to_equal('#output', 'initial value')

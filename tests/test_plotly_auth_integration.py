from dash.dependencies import Input, Output, State, Event
import dash
import dash_html_components as html
import dash_core_components as dcc
from multiprocessing import Value
import os
import time
import re
import itertools
import plotly.plotly as py

from .IntegrationTests import IntegrationTests
from .utils import assert_clean_console, switch_windows
from .users import users
from dash_auth import plotly_auth


class Tests(IntegrationTests):
    def setup_app(self, url_base_pathname=None, skip_visit=False,
                  sharing='private'):
        app = dash.Dash(__name__, url_base_pathname=url_base_pathname)
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

        auth = plotly_auth.PlotlyAuth(
            app,
            'integration-test',
            sharing,
            (
                'http://localhost:8050{}'.format(url_base_pathname)
                if url_base_pathname else oauth_urls
            )
        )

        self.startServer(app, skip_visit=skip_visit)

        return app, auth

    def plotly_auth_login_flow(self, username, pw,
                               url_base_pathname=None, oauth_urls=None):
        os.environ['PLOTLY_USERNAME'] = users['creator']['username']
        os.environ['PLOTLY_API_KEY'] = users['creator']['api_key']

        app, _ = self.setup_app(url_base_pathname)

        try:
            el = self.wait_for_element_by_css_selector('#dash-auth--login__container')
        except Exception as e:
            print(self.wait_for_element_by_tag_name('body').html)
            raise e

        self.wait_for_element_by_css_selector(
            '#dash-auth--login__button').click()
        switch_windows(self.driver)
        self.wait_for_element_by_css_selector(
            '#js-auth-modal-signin-username'
        ).send_keys(username)

        self.wait_for_element_by_css_selector(
            '#js-auth-modal-signin-password'
        ).send_keys(pw)

        self.wait_for_element_by_css_selector(
            '#js-auth-modal-signin-submit').click()

        # wait for oauth screen
        self.wait_for_element_by_css_selector('input[name="allow"]').click()

    def private_app_unauthorized(self, url_base_pathname=None, oauth_urls=None):
        self.plotly_auth_login_flow(
            users['viewer']['username'],
            users['viewer']['pw'],
            url_base_pathname=url_base_pathname,
            oauth_urls=oauth_urls
        )
        el = self.wait_for_element_by_css_selector(
            '#dash-auth--authorization__denied')
        self.assertEqual(el.text, 'You are not authorized to view this app')
        switch_windows(self.driver)
        self.driver.refresh()
        # login screen should still be there
        self.wait_for_element_by_css_selector(
            '#dash-auth--login__container')

    def private_app_authorized(self, url_base_pathname=None, oauth_urls=None):
        self.plotly_auth_login_flow(
            users['creator']['username'],
            users['creator']['pw'],
            url_base_pathname,
        )
        switch_windows(self.driver)
        try:
            el = self.wait_for_element_by_css_selector('#output')
        except:
            print((self.driver.find_element_by_tag_name('body').html))
        self.assertEqual(el.text, 'initial value')

    def test_private_app_authorized_index(self):
        self.private_app_authorized('/')

    def test_private_app_authorized_route(self):
        self.private_app_authorized('/my-app/')

    def test_private_app_unauthorized_index(self):
        self.private_app_unauthorized('/')

    def test_private_app_unauthorized_route(self):
        self.private_app_unauthorized('/my-app/')


    def test_private_app_authorized_index_multiple_oauth_urls(self):
        self.private_app_authorized(
            '/',
            oauth_urls=[
                'http://test-domain.plotly.systems:8050/',
                'http://localhost:8050/'
            ]
        )

    def secret_app_unauthorized(self, url_base_pathname=None):
        app, auth = self.setup_app(url_base_pathname, skip_visit=True,
                                   sharing='secret')

        self.driver.get('http://localhost:8050{}'
                        '?share_key=bad'.format(url_base_pathname))

        # Should show login screen
        self.wait_for_element_by_css_selector(
            '#dash-auth--login__container')

    def secret_app_authorized(self, url_base_pathname=None):
        app, auth = self.setup_app(url_base_pathname, skip_visit=True,
                                   sharing='secret')

        key = auth._dash_app['share_key']

        self.driver.get('http://localhost:8050{}'
                        '?share_key={}'.format(url_base_pathname, key))

        try:
            el = self.wait_for_element_by_css_selector('#output')
        except:
            print((self.driver.find_element_by_tag_name('body').html))

        # Note: this will only work if both the initial and subsequent
        # requests (e.g. to get the layoout) succeed.
        self.assertEqual(el.text, 'initial value')

    def test_secret_app_unauthorized_index(self):
        self.secret_app_unauthorized('/')

    def test_secret_app_unauthorized_route(self):
        self.secret_app_unauthorized('/my-app/')

    def test_secret_app_authorized_index(self):
        self.secret_app_authorized('/')

    def test_secret_app_authorized_route(self):
        self.secret_app_authorized('/my-app/')

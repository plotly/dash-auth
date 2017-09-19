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
from .utils import assert_clean_console, invincible, switch_windows, wait_for
from .users import users
from dash_auth import plotly_auth


class Tests(IntegrationTests):
    def plotly_auth_login_flow(self, username, pw, url_base_pathname):
        os.environ['PLOTLY_USERNAME'] = users['creator']['username']
        os.environ['PLOTLY_API_KEY'] = users['creator']['api_key']
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

        plotly_auth.PlotlyAuth(
            app,
            'integration-test',
            'private',
            'http://localhost:8050{}'.format(url_base_pathname)
        )

        self.startServer(app)

        time.sleep(10)
        try:
            el = self.wait_for_element_by_id('dash-auth--login__container')
        except Exception as e:
            print(self.wait_for_element_by_tag_name('body').html)
            raise e

        self.driver.find_element_by_id('dash-auth--login__button').click()
        time.sleep(5)
        switch_windows(self.driver)
        time.sleep(20)
        self.wait_for_element_by_id(
            'js-auth-modal-signin-username'
        ).send_keys(username)

        self.driver.find_element_by_id(
            'js-auth-modal-signin-password'
        ).send_keys(pw)

        self.driver.find_element_by_id('js-auth-modal-signin-submit').click()

        # wait for oauth screen
        time.sleep(5)
        self.wait_for_element_by_css_selector('input[name="allow"]').click()

    def private_app_unauthorized(self, url_base_pathname):
        self.plotly_auth_login_flow(
            users['viewer']['username'],
            users['viewer']['pw'],
            url_base_pathname
        )
        time.sleep(5)
        el = self.wait_for_element_by_id('dash-auth--authorization__denied')
        self.assertEqual(el.text, 'You are not authorized to view this app')
        switch_windows(self.driver)
        self.driver.refresh()
        # login screen should still be there
        self.wait_for_element_by_id('dash-auth--login__container')

    def private_app_authorized(self, url_base_pathname):
        self.plotly_auth_login_flow(
            users['creator']['username'],
            users['creator']['pw'],
            url_base_pathname
        )
        switch_windows(self.driver)
        time.sleep(5)
        try:
            el = self.wait_for_element_by_id('output')
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

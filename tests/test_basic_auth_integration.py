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
import requests

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException

from .IntegrationTests import IntegrationTests
from .utils import assert_clean_console, switch_windows
from dash_auth import basic_auth


TEST_USERS = {
    'valid': [
        ['hello', 'world']
    ],
    'invalid': [
        ['hello', 'password']
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

        auth = basic_auth.BasicAuth(
            app,
            TEST_USERS['valid']
        )

        self.startServer(app, skip_visit=True)

        self.assertEqual(
            requests.get('http://localhost:8050').status_code,
            401
        )

        # login using the URL instead of the alert popup
        # selenium has no way of accessing the alert popup
        self.driver.get('http://hello:world@localhost:8050')

        # the username:password@host url doesn't work right now for dash
        # routes, but it saves the credentials as part of the browser.
        # visiting the page again will use the saved credentials
        self.driver.get('http://localhost:8050')
        el = self.wait_for_element_by_css_selector('#output')
        self.wait_for_text_to_equal('#output', 'initial value')

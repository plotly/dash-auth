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

from IntegrationTests import IntegrationTests
from utils import assert_clean_console, invincible, switch_windows, wait_for
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
    def setUp(self):
        def wait_for_element_by_id(id):
            wait_for(lambda: None is not invincible(
                lambda: self.driver.find_element_by_id(id)
            ))
            return self.driver.find_element_by_id(id)
        self.wait_for_element_by_id = wait_for_element_by_id

        def wait_for_element_by_css_selector(css_selector):
            wait_for(lambda: None is not invincible(
                lambda: self.driver.find_element_by_css_selector(css_selector)
            ))
            return self.driver.find_element_by_css_selector(css_selector)
        self.wait_for_element_by_css_selector = wait_for_element_by_css_selector


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

        self.startServer(app)
        self.assertEqual(
            requests.get('http://localhost:8050').status_code,
            401
        )
        with self.assertRaises(NoSuchElementException):
            self.driver.find_element_by_id('output')

        # login using the URL instead of the alert popup
        # selenium has no way of accessing the alert popup
        self.driver.get('http://hello:world@localhost:8050')

        # the username:password@host url doesn't work right now for dash routes,
        # but it saves the credentials as part of the browser.
        # visiting the page again will use the saved credentials
        self.driver.get('http://localhost:8050')
        time.sleep(5)
        el = self.wait_for_element_by_id('output')
        self.assertEqual(el.text, 'initial value')

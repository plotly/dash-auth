# -*- coding: utf-8 -*-
import unittest

import flask
from dash.dependencies import Input, Output
import dash
try:
    from dash import html, dcc
except ImportError:
    import dash_html_components as html
    import dash_core_components as dcc
import os
import time
from dash.exceptions import PreventUpdate

from .IntegrationTests import IntegrationTests
from .utils import switch_windows
from .users import users
from dash_auth import plotly_auth


class Tests(IntegrationTests):
    def setup_app(self, url_base_pathname, skip_visit=False,
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

        # noinspection PyUnresolvedReferences
        auth = plotly_auth.PlotlyAuth(
            app,
            'integration-test',
            sharing,
            'http://localhost:8050{}'.format(url_base_pathname)
        )

        self.startServer(app, skip_visit=skip_visit)

        return app, auth

    def plotly_auth_login_flow(self, username, pw,
                               url_base_pathname, oauth_urls=None):
        os.environ['PLOTLY_USERNAME'] = users['creator']['username']
        os.environ['PLOTLY_API_KEY'] = users['creator']['api_key']

        app, _ = self.setup_app(url_base_pathname)

        self._login_flow(username, pw)

    def _login_flow(self, username, pw):
        try:
            self.wait_for_element_by_css_selector(
                '#dash-auth--login__container')
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
            time.sleep(3)
            # wait for oauth screen
            self.wait_for_element_by_css_selector('input[name="allow"]').click()
        except Exception as e:
            print(self.wait_for_element_by_css_selector('body').text)
            raise e

    def private_app_unauthorized(self, url_base_pathname=None,
                                 oauth_urls=None):
        self.plotly_auth_login_flow(
            users['viewer']['username'],
            users['viewer']['pw'],
            url_base_pathname,
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

    def private_app_authorized(self, url_base_pathname, oauth_urls=None):
        self.plotly_auth_login_flow(
            users['creator']['username'],
            users['creator']['pw'],
            url_base_pathname,
        )
        switch_windows(self.driver)
        try:
            self.wait_for_element_by_css_selector('#output')
        except Exception:
            print(self.driver.find_element_by_tag_name(
                'body').get_attribute('innerHTML'))
        self.wait_for_text_to_equal('#output', 'initial value')

    def test_private_app_authorized_index(self):
        self.private_app_authorized('/')

    @unittest.skip('broken, unknown commit')
    def test_private_app_authorized_route(self):
        self.private_app_authorized('/my-app/')

    def test_private_app_unauthorized_index(self):
        self.private_app_unauthorized('/')

    @unittest.skip('broken, unknown commit')
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

    def secret_app_unauthorized(self, url_base_pathname):
        app, auth = self.setup_app(url_base_pathname, skip_visit=True,
                                   sharing='secret')

        self.driver.get('http://localhost:8050{}'
                        '?share_key=bad'.format(url_base_pathname))

        # Should show login screen
        self.wait_for_element_by_css_selector(
            '#dash-auth--login__container')

    def secret_app_authorized(self, url_base_pathname):
        app, auth = self.setup_app(url_base_pathname, skip_visit=True,
                                   sharing='secret')

        key = auth._dash_app['share_key']

        self.driver.get('http://localhost:8050{}'
                        '?share_key={}'.format(url_base_pathname, key))

        try:
            self.wait_for_element_by_css_selector('#output')
        except Exception:
            print((self.driver.find_element_by_tag_name('body').html))

        # Note: this will only work if both the initial and subsequent
        # requests (e.g. to get the layoout) succeed.

        self.wait_for_text_to_equal('#output', 'initial value')

    def test_secret_app_unauthorized_index(self):
        self.secret_app_unauthorized('/')

    def test_secret_app_unauthorized_route(self):
        self.secret_app_unauthorized('/my-app/')

    def test_secret_app_authorized_index(self):
        self.secret_app_authorized('/')

    def test_secret_app_authorized_route(self):
        self.secret_app_authorized('/my-app/')

    @unittest.skip('Broken on circle')
    def test_logout(self):
        os.environ['PLOTLY_USERNAME'] = users['creator']['username']
        os.environ['PLOTLY_API_KEY'] = users['creator']['api_key']

        app = dash.Dash()
        auth = plotly_auth.PlotlyAuth(
            app, 'integration-test', 'public',
            ['http://localhost:8050/', 'http://127.0.0.1:8050/'])

        logout_label = 'Press to logout'

        btn_style = {
            'backgroundColor': 'red',
            'padding': '16px',
            'borderRadius': '8px',
            'border': 'none'
        }

        app.layout = html.Div([
            html.Div('content', id='content'),
            auth.create_logout_button(
                id='logout-btn',
                label=logout_label,
                style=btn_style)
        ], id='container')

        self.startServer(app)

        username = users['viewer']['username']
        pw = users['viewer']['pw']

        self._login_flow(username, pw)

        switch_windows(self.driver)
        time.sleep(2)

        btn = self.wait_for_element_by_css_selector('#logout-btn')

        padding = btn.value_of_css_property('padding')
        self.assertEqual(btn_style['padding'], padding)

        self.assertEqual(logout_label, btn.text)
        btn.click()
        time.sleep(1)

        self.assertTrue(auth._app_url[0] in self.driver.current_url)

    def test_user_cookies(self):
        os.environ['PLOTLY_USERNAME'] = users['creator']['username']
        os.environ['PLOTLY_API_KEY'] = users['creator']['api_key']

        app = dash.Dash()
        auth = plotly_auth.PlotlyAuth(
            app,
            'integration-test',
            'private',
            'http://localhost:8050/'
        )

        app.layout = html.Div([
            html.Div(id='username'),
            html.Button('click me', id='btn'),
            html.Div(id='authorized')],
            id='container')

        @app.callback(Output('username', 'children'),
                      [Input('username', 'id')])
        def _give_name(_):
            username = auth.get_username()
            return username

        @auth.is_authorized_hook
        def _is_authorized(_):
            perms = {'click_button': True}
            auth.set_user_data(perms)
            return True

        @app.callback(Output('authorized', 'children'),
                      [Input('btn', 'n_clicks')])
        def _check_perms(n_clicks):
            if n_clicks:
                perms = auth.get_user_data()
                perm_click_button = perms.get('click_button')
                if not perm_click_button:
                    return 'unauthorized'
                else:
                    return 'authorized'

        self.startServer(app)

        self._login_flow(users['creator']['username'], users['creator']['pw'])
        switch_windows(self.driver)

        self.wait_for_text_to_equal('#username', 'dash-test-user')

        btn = self.wait_for_element_by_css_selector('#btn')
        btn.click()
        self.wait_for_text_to_equal('#authorized', 'authorized')

    def test_logout_url(self):
        os.environ['DASH_LOGOUT_URL'] = '/_logout'
        app = dash.Dash(__name__)
        auth = plotly_auth.PlotlyAuth(
            app, 'integration-test', 'public',
            ['http://localhost:8050/', 'http://127.0.0.1:8050/'])

        @app.server.route('/_logout', methods=['POST'])
        def on_logout():
            rep = flask.redirect('/logged-out')
            rep.set_cookie('logout-cookie', '', 0)
            return rep

        app.layout = html.Div([
            html.H2('Logout test'),
            dcc.Location(id='location'),
            html.Div(id='content'),
        ])

        @app.callback(Output('content', 'children'),
                      [Input('location', 'pathname')])
        def on_location(location_path):
            if location_path is None:
                raise PreventUpdate

            if 'logged-out' in location_path:
                return 'Logged out'
            else:

                @flask.after_this_request
                def _insert_cookie(rep):
                    rep.set_cookie('logout-cookie', 'logged-in')
                    return rep

                return auth.create_logout_button()

        self.startServer(app)
        btn = self.wait_for_element_by_css_selector('#logout-btn')
        btn.click()

        self.wait_for_text_to_equal('#content', 'Logged out')

        self.assertFalse(self.driver.get_cookie('logout-cookie'))
        del os.environ['DASH_LOGOUT_URL']

from __future__ import absolute_import
import time
import unittest
import dash
try:
    from dash import html
except ImportError:
    import dash_html_components as html
import os
import six
from six.moves import http_cookies
from six import iteritems
import dash_auth
from dash_auth import plotly_auth
from dash_auth.plotly_auth import PlotlyAuth
from .users import users

if six.PY3:
    from unittest import mock
else:
    import mock

endpoints = {
    'protected': {
        'get': [
            '/_dash-layout', '/_dash-routes', '/_dash-dependencies',
            '/_dash-component-suites/dash_html_components/dash_html_components.min.js',
            '/static/', '/assets/', '/_favicon.ico', '/_reload-hash',
        ],
        'post': ['/_dash-update-component']
    },
    'unprotected': {
        'get': ['/', '/some-url'],
        'post': []
    }
}


def get_cookie(res, cookie_name):
    headers = res.headers.to_list()
    set_cookie_strings = [h for h in headers if (
        h[0] == 'Set-Cookie' and cookie_name in h[1]
    )]
    try:
        cookie_string = set_cookie_strings[0][1]
    except IndexError as e:
        print(cookie_name)
        for header in headers:
            print(header)
        print(set_cookie_strings)
        raise e

    cookie = http_cookies.SimpleCookie(cookie_string)
    access_granted_cookie = cookie[list(cookie.keys())[0]].value
    return access_granted_cookie


def create_apps():
    app_permissions = ['public', 'private', 'secret']
    apps = {k: dash.Dash(k) for k in app_permissions}
    for app in list(apps.values()):
        app.scripts.config.serve_locally = True
        app.layout = html.Div()
    auths = {
        k: PlotlyAuth(
            apps[k],
            '{}-app-test'.format(k),
            k,
            'http://localhost:5000'
        ) for k in app_permissions
    }
    apps['unregistered'] = dash.Dash('unregistered')
    apps['unregistered'].scripts.config.serve_locally = True
    return apps, auths


class ProtectedViewsTest(unittest.TestCase):
    def setUp(self):
        os.environ['PLOTLY_USERNAME'] = users['creator']['username']
        os.environ['PLOTLY_API_KEY'] = users['creator']['api_key']
        self.longMessage = True

    def test_protecting_all_views(self):
        apps = create_apps()[0]
        self.assertEqual((
            len(endpoints['protected']['get']) +
            len(endpoints['unprotected']['get']) +
            len(endpoints['protected']['post']) +
            len(endpoints['unprotected']['post'])),
            len([k for k in apps['unregistered'].server.url_map.iter_rules()])
        )

    def test_unauthenticated_view(self):
        apps = create_apps()[0]
        for app_name in ['unregistered']:
            app = apps[app_name]
            app.layout = html.Div()
            client = app.server.test_client()
            for endpoint in (endpoints['protected']['get'] +
                             endpoints['unprotected']['get']):
                res = client.get(endpoint)
                test_name = '{} at {} ({})'.format(
                    res.status_code, endpoint, app_name
                )

                self.assertEqual(res.status_code, 200, test_name)

    @unittest.skip('broken, unknown commit')
    def test_403_on_protected_endpoints_without_cookie(self):
        apps = create_apps()[0]
        for app in [apps['private'], apps['public']]:
            app.layout = html.Div()
            client = app.server.test_client()
            for endpoint in endpoints['protected']['get']:
                res = client.get(endpoint)
                self.assertEqual(res.status_code, 403, endpoint)

            for endpoint in endpoints['unprotected']['get']:
                res = client.get(endpoint)
                self.assertEqual(res.status_code, 200, endpoint)

            # TODO - check 200 on post of unprotected endpoints?
            for endpoint in endpoints['protected']['post']:
                res = client.post(endpoint)
                self.assertEqual(res.status_code, 403, endpoint)

    def check_endpoints(self, auth, app, oauth_token, cookies=tuple(),
                        all_200=False):
        def get_client():
            client = app.server.test_client()
            client.set_cookie(
                '/',
                'plotly_oauth_token',
                oauth_token
            )
            for cookie in cookies:
                client.set_cookie('/', cookie['name'], cookie['value'])
            return client

        for endpoint in (endpoints['unprotected']['get'] +
                         endpoints['protected']['get']):
            client = get_client()  # use a fresh client for every endpoint
            res = client.get(endpoint)
            test_name = '{} at {} as {} on {} ({})'.format(
                res.status_code, endpoint, oauth_token, auth._dash_app['fid'],
                auth._sharing
            )
            if (auth._dash_app['fid'] is None or
                    auth._sharing == 'public' or
                    oauth_token == users['creator']['oauth_token'] or
                    endpoint in endpoints['unprotected']['get'] or
                    all_200):
                self.assertEqual(res.status_code, 200, test_name)
            elif auth._sharing in ['private']:
                self.assertEqual(res.status_code, 403, test_name)
        return res

    @unittest.skip('broken, unknown commit')
    def test_protected_endpoints_with_auth_cookie(self):
        apps, auths = create_apps()
        for user_attributes in list(users.values()):
            for app_name, app in iteritems(apps):
                if app_name != 'unregistered':
                    app.layout = html.Div()
                    self.check_endpoints(
                        auths[app_name],
                        app,
                        user_attributes['oauth_token'],
                    )

    def test_share_key(self):
        apps, auths = create_apps()
        app = apps['secret']
        auth = auths['secret']

        key = 'testsharekey'
        auth._dash_app = {'share_key': key}

        for endpoint in endpoints['protected']['get']:
            client = app.server.test_client()

            endpoint_with_key = '{}?share_key=bad'.format(endpoint)
            res = client.get(endpoint_with_key)
            self.assertEqual(res.status_code, 403, endpoint)

            endpoint_with_key = '{}?share_key={}'.format(endpoint, key)
            res = client.get(endpoint_with_key)
            self.assertEqual(res.status_code, 200, endpoint)

            self.assertTrue(get_cookie(res, PlotlyAuth.AUTH_COOKIE_NAME))

            # Given the cookie, we can now make a request with no other auth:
            res = client.get(endpoint)
            self.assertEqual(res.status_code, 200, endpoint)

    @unittest.skip('broken by e612142c530ee0375303fc88b646d534284c1209')
    def test_permissions_can_change(self):
        app_name = 'private-flip-flop-app-test'
        app_url = 'http://localhost:5000'
        app = dash.Dash()
        app.scripts.config.serve_locally = True
        auth = PlotlyAuth(app, app_name, 'private', app_url)
        app.layout = html.Div()
        auth.config['permissions_cache_expiry'] = 30
        auth.create_access_codes()
        viewer_token = users['viewer']['oauth_token']
        with mock.patch('dash_auth.plotly_auth.check_view_access',
                        wraps=plotly_auth.check_view_access) as \
                wrapped:

            n_endpoints = (
                len(endpoints['protected']['get']) +
                len(endpoints['unprotected']['get']))

            # sanity check the endpoints when the app is private
            self.check_endpoints(auth, app, viewer_token)
            self.assertEqual(wrapped.call_count, n_endpoints)

            # make app public
            dash_auth.plotly_auth.create_or_overwrite_dash_app(
                app_name, 'public', app_url
            )
            res = self.check_endpoints(auth, app, viewer_token, all_200=True)
            self.assertEqual(wrapped.call_count, n_endpoints * 2)

            # The last access granted response contained a cookie that grants
            # the user access for 30 seconds (5 minutes by default)
            # without making an API call to plotly.
            # Include this cookie in the response and verify that it grants
            # the user access up until the expiration date
            access_granted_cookie = get_cookie(
                res, PlotlyAuth.AUTH_COOKIE_NAME)
            self.assertEqual(
                access_granted_cookie,
                auth._access_codes['access_granted']
            )

            plotly_auth.create_or_overwrite_dash_app(
                app_name, 'private', app_url
            )

            # Even though the app is private, the viewer will still get 200s
            access_cookie = (
                {'name': PlotlyAuth.AUTH_COOKIE_NAME,
                 'value': access_granted_cookie},
            )
            self.check_endpoints(
                auth, app, viewer_token, access_cookie, all_200=True
            )
            self.assertEqual(wrapped.call_count, n_endpoints * 2)

            # But after 30 seconds, the auth token will expire,
            # and the user will be denied access
            time.sleep(5)
            self.check_endpoints(auth, app, viewer_token,
                                 access_cookie, all_200=True)
            self.assertEqual(wrapped.call_count, n_endpoints * 2)
            time.sleep(26)
            self.check_endpoints(auth, app, viewer_token, access_cookie)
            self.assertEqual(wrapped.call_count, n_endpoints * 3)

    @unittest.skip('broken by e612142c530ee0375303fc88b646d534284c1209')
    def test_auth_cookie_caches_calls_to_plotly(self):
        app = dash.Dash()
        app.scripts.config.serve_locally = True
        auth = PlotlyAuth(
            app,
            'private-cookie-test',
            'private',
            'http://localhost:5000'
        )
        app.layout = html.Div()

        creator = users['creator']['oauth_token']
        with mock.patch('dash_auth.plotly_auth.check_view_access',
                        wraps=plotly_auth.check_view_access) as wrapped:
            self.check_endpoints(auth, app, creator)
            res = self.check_endpoints(auth, app, creator)

            n_endpoints = (
                len(endpoints['protected']['get']) +
                len(endpoints['unprotected']['get']))

            self.assertEqual(wrapped.call_count, n_endpoints * 2)

            access_granted_cookie = get_cookie(
                res,
                PlotlyAuth.AUTH_COOKIE_NAME)
            self.check_endpoints(auth, app, creator, (
                {'name': PlotlyAuth.AUTH_COOKIE_NAME,
                 'value': access_granted_cookie},
            ))
            self.assertEqual(wrapped.call_count, n_endpoints * 2)

            # Regenerate tokens with a shorter expiration
            # User's won't actually do this in practice, we're
            # just doing it to shorten up the expiration from 5 min
            # to 10 seconds
            auth.config['permissions_cache_expiry'] = 10
            auth.create_access_codes()
            res = self.check_endpoints(auth, app, creator)
            self.assertEqual(wrapped.call_count,
                             n_endpoints * 3)

            # Using the same auth cookie should prevent an
            # additional access call
            access_granted_cookie = get_cookie(
                res, PlotlyAuth.AUTH_COOKIE_NAME)
            self.check_endpoints(auth, app, creator, (
                {'name': PlotlyAuth.AUTH_COOKIE_NAME,
                 'value': access_granted_cookie},
            ))
            self.assertEqual(
                wrapped.call_count,
                (n_endpoints * 3))

            # But after the expiration time (10 seconds), another call to
            # plotly should be made
            time.sleep(10)
            self.check_endpoints(auth, app, creator)
            self.assertEqual(
                wrapped.call_count,
                (n_endpoints * 4))


class LoginFlow(unittest.TestCase):
    def login_success(self):
        app = dash.Dash()
        app.config.scripts.serve_locally = True
        PlotlyAuth(
            app,
            'test-auth-login-flow',
            'private',
            'https://dash-auth-app.herokuapp.com'
        )
        app.layout = html.Div()
        client = app.server.test_client()
        csrf_token = get_cookie(client.get('/'), '_csrf_token')
        client.set_cookie('/', '_csrf_token', csrf_token)
        oauth_token = users['creator']['oauth_token']
        res = client.post('_login', headers={
            'Authorization': 'Bearer {}'.format(oauth_token),
            'X-CSRFToken': csrf_token
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            get_cookie(res, 'plotly_oauth_token'),
            oauth_token
        )

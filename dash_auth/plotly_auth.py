from __future__ import absolute_import
import flask
import json

from .oauth import OAuthBase

from . import api_requests, utils


class PlotlyAuth(OAuthBase):
    AUTH_COOKIE_NAME = 'plotly_auth'
    TOKEN_COOKIE_NAME = 'plotly_oauth_token'

    def __init__(self, app, app_name, sharing, app_url):
        super(PlotlyAuth, self).__init__(app, app_url)

        self._fid = utils.create_or_overwrite_dash_app(
            app_name, sharing, app_url
        )
        self._oauth_client_id = utils.create_or_overwrite_oauth_app(
            app_url, app_name
        )['client_id']
        self._sharing = sharing

    def html(self, script):
        return ('''
            <!doctype html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>Log In</title>
            </head>
            <body>
              <div id="react-root"></div>
            </body>
            <script id="_auth-config" type="application/json">
            {}
            </script>
            <script type="text/javascript">{}</script>
            </html>
        '''.format(
            json.dumps({
                'oauth_client_id': self._oauth_client_id,
                'plotly_domain': api_requests.config('plotly_domain'),
                'requests_pathname_prefix':
                    self._app.config['requests_pathname_prefix']
            }),
            script)
        )

    def login_api(self):
        oauth_token = flask.request.get_json()['access_token']
        res = api_requests.get(
            '/v2/users/current',
            headers={'Authorization': 'Bearer {}'.format(oauth_token)},
        )
        try:
            res.raise_for_status()
        except Exception as e:
            print(res.content)
            raise e
        response = flask.Response(
            json.dumps(res.json()),
            mimetype='application/json',
            status=res.status_code
        )

        self.set_cookie(
            response=response,
            name='plotly_oauth_token',
            value=oauth_token,
            max_age=None
        )

        return response

    def check_view_access(self, oauth_token):
        return utils.check_view_access(oauth_token, self._fid)

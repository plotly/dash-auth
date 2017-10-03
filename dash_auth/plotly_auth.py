from __future__ import absolute_import
import flask
import json
from six import iteritems

from .oauth import OAuthBase

from . import api_requests


class PlotlyAuth(OAuthBase):
    AUTH_COOKIE_NAME = 'plotly_auth'
    TOKEN_COOKIE_NAME = 'plotly_oauth_token'

    def __init__(self, app, app_name, sharing, app_url):
        super(PlotlyAuth, self).__init__(app, app_url)

        self._fid = create_or_overwrite_dash_app(
            app_name, sharing, app_url
        )
        self._oauth_client_id = create_or_overwrite_oauth_app(
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
        return check_view_access(oauth_token, self._fid)


def create_or_overwrite_dash_app(filename, sharing, app_url):
    required_args = {
        'filename': filename,
        'sharing': sharing,
        'app_url': app_url
    }
    for arg_name, arg_value in iteritems(required_args):
        if arg_value is None:
            raise Exception('{} is required'.format(arg_name))
    if sharing not in ['private', 'public']:
        raise Exception(
            "The privacy argument must be equal "
            "to 'private' or 'public'.\n"
            "You supplied '{}'".format(sharing)
        )
    payload = json.dumps({
        'filename': filename,
        'share_key_enabled': True if sharing == 'secret' else False,
        'world_readable': True if sharing == 'public' else False,
        'app_url': app_url
    })

    res_lookup = api_requests.get('/v2/files/lookup?path={}'.format(filename))
    if res_lookup.status_code == 404:
        # TODO - Better request handling
        res_create = api_requests.post('/v2/dash-apps', data=payload)
        try:
            res_create.raise_for_status()
        except Exception as e:
            print(payload)
            print(res_create.content)
            raise e
        fid = res_create.json()['file']['fid']
        return fid
    elif res_lookup.status_code == 200:
        fid = res_lookup.json()['fid']
        res_update = api_requests.patch(
            '/v2/dash-apps/{}'.format(fid),
            data=payload
        )
        try:
            res_update.raise_for_status()
        except Exception as e:
            print(payload)
            print(res_update.content)
            raise e
        return fid
    else:
        print(res_lookup.content)
        res_lookup.raise_for_status()


def create_or_overwrite_oauth_app(app_url, name):
    redirect_uri = '{}/_oauth-redirect'.format(app_url.strip('/'))
    request_data = {
        'data': json.dumps({
            'name': name,
            'client_type': 'public',
            'authorization_grant_type': 'implicit',
            'redirect_uris': redirect_uri,
        })
    }

    # Check if app already exists.
    # If it does, then update it.
    # If it doesn't, then create a new one.
    res = api_requests.get(
        '/v2/oauth-apps/lookup',
        params={'name': name},
    )
    try:
        res.raise_for_status()
    except Exception as e:
        print(res.content)
        raise e
    apps = res.json()
    if len(apps) > 1:
        raise Exception(
            'There are more than one oauth apps with the name {}.'.format(name)
        )
    elif len(apps) == 1:
        oauth_app_id = apps[0]['id']
        res = api_requests.patch(
            '/v2/oauth-apps/{}'.format(oauth_app_id),
            **request_data
        )
    else:
        res = api_requests.post('/v2/oauth-apps', **request_data)

    try:
        res.raise_for_status()
    except Exception as e:
        print(res.content)
        raise e

    return res.json()


def check_view_access(oauth_token, fid):
    res = api_requests.get(
        '/v2/files/{}'.format(fid),
        headers={'Authorization': 'Bearer {}'.format(oauth_token)}
    )
    if res.status_code == 200:
        return True
    elif res.status_code == 404:
        return False
    else:
        # TODO - Dash exception
        raise Exception('Failed request to plotly')

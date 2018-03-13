from __future__ import absolute_import
import json
from six import iteritems

from . import api_requests


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

def check_share_key_access(share_key, fid):
    res = api_requests.get('/v2/files/{}?share_key='.format(fid, share_key))

    if res.status_code == 200:
        return True
    elif res.status_code == 404:
        return False
    else:
        # TODO - Dash exception
        raise Exception('Failed request to plotly')

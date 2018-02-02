from __future__ import absolute_import
import copy
import os
import plotly
from retrying import retry
import requests

# API requests get their config from the environment.
# If variables aren't there, then they check the
# plotly.tools.get_credentials_file


def credential(key):
    if key in os.environ:
        return os.environ[key]
    elif key.upper() in os.environ:
        return os.environ[key.upper()]
    else:
        return plotly.tools.get_credentials_file()[key.replace('plotly_', '')]


def config(key):
    if key in os.environ:
        value = os.environ[key]
    elif key.upper() in os.environ:
        value = os.environ[key.upper()]
    else:
        value = plotly.tools.get_config_file()[key]

    # Handle PLOTLY_SSL_VERIFICATION which is True or False but a
    # string in environ
    if value == 'False':
        return False
    elif value == 'True':
        return True
    else:
        return value


HEADERS = {
    'plotly-client-platform': 'dash-auth',
    'content-type': 'application/json'
}


def _modify_request_kwargs(request_kwargs):
    copied_kwargs = copy.deepcopy(request_kwargs)
    if 'headers' in request_kwargs:
        copied_kwargs['headers'].update(HEADERS)
    else:
        copied_kwargs['headers'] = HEADERS

    if 'Authorization' not in copied_kwargs['headers']:
        copied_kwargs['auth'] = (
            credential('plotly_username'),
            credential('plotly_api_key'),)

    if 'DASH_STREAMBED_DIRECT_IP' in os.environ:
        copied_kwargs['verify'] = False
    else:
        copied_kwargs['verify'] = config('plotly_ssl_verification')

    return copied_kwargs


def _create_method(method_name):
    def request(path, api_key_auth=True, **request_kwargs):
        copied_kwargs = _modify_request_kwargs(request_kwargs)
        if 'DASH_STREAMBED_DIRECT_IP' in os.environ:
            base_url = 'https://{}'.format(config('dash_streambed_direct_ip'))
        else:
            base_url = config('plotly_api_domain')

        request_method = getattr(requests, method_name)

        def check_request_before_returning(*args, **kwargs):
            resp = request_method(*args, **kwargs)

            # 404's are the only accepted "error" code
            # as we use this to check if a file exists or not
            if resp.status_code != 404:
                resp.raise_for_status()
            return resp

        request_with_retry = retry(
            wait_random_min=100,
            wait_random_max=1000,
            wait_exponential_max=10000,
            stop_max_delay=30000
        )(check_request_before_returning)

        return request_with_retry(
            '{}{}'.format(base_url, path),
            **copied_kwargs
        )
    return request


post = _create_method('post')
patch = _create_method('patch')
get = _create_method('get')

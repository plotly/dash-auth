from __future__ import absolute_import
import copy
import logging
import os
import socket
import sys

import chart_studio
from retrying import retry
import requests

try:
    import http.client as http_client
except ImportError:
    # Python 2
    import httplib as http_client

try:
    from urlparse import urlparse
except ImportError:
    from urllib.parse import urlparse


# API requests get their config from the environment.
# If variables aren't there, then they check the
# chart_studio.tools.get_credentials_file


def credential(key):
    if key in os.environ:
        return os.environ[key]
    elif key.upper() in os.environ:
        return os.environ[key.upper()]
    else:
        return chart_studio.tools.get_credentials_file()[
            key.replace('plotly_', '')
        ]


def config(key):
    if key in os.environ:
        value = os.environ[key]
    elif key.upper() in os.environ:
        value = os.environ[key.upper()]
    else:
        value = chart_studio.tools.get_config_file().get(key)

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


def debug_requests_on(url, **kwargs):
    # Adapted from https://stackoverflow.com/a/24588289/4142536
    http_client.HTTPConnection.debuglevel = logging.DEBUG
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True
    requests_log.addHandler(logging.StreamHandler(sys.stdout))

    # Log some additional info
    print('Attempting connection at {}'.format(url))
    parsed_url = urlparse(url)
    try:
        print('gettaddrinfo: {}'.format(
            socket.getaddrinfo(parsed_url.netloc, parsed_url.scheme)
        ))
    except Exception as e:
        print('gettaddrinfo failed')
        print(e)


def debug_requests_off():
    http_client.HTTPConnection.debuglevel = 0
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.NOTSET)
    requests_log.propagate = False


def _create_method(method_name):
    def request(path, api_key_auth=True, **request_kwargs):
        copied_kwargs = _modify_request_kwargs(request_kwargs)
        if 'DASH_STREAMBED_DIRECT_IP' in os.environ:
            base_url = 'https://{}'.format(config('dash_streambed_direct_ip'))
        else:
            base_url = config('plotly_api_domain')

        request_method = getattr(requests, method_name)

        VALID_4XX_STATUS_CODES = [404, 405]

        def check_request_before_returning(url, **kwargs):
            resp = request_method(url, **kwargs)

            # 404's are the only accepted "error" code
            # as we use this to check if a file exists or not
            if resp.status_code not in VALID_4XX_STATUS_CODES:
                resp.raise_for_status()
            return resp

        request_with_retry = retry(
            wait_random_min=100,
            wait_random_max=1000,
            wait_exponential_max=10000,
            stop_max_delay=30000
        )(check_request_before_returning)

        def retry_request_with_logs(url, **kwargs):
            debug_requests_off()
            try:
                return request_with_retry(url, **kwargs)
            except BaseException:
                # request-level errors include ConnectionError
                print(sys.exc_info())

                # do the request one last time with logs
                debug_requests_on(url)
                resp = request_method(url, **kwargs)
                if resp.status_code not in VALID_4XX_STATUS_CODES:
                    resp.raise_for_status()

                # in the off chance that it succeeded on its last request
                # return the response
                return resp

        return retry_request_with_logs(
            '{}{}'.format(base_url, path),
            **copied_kwargs
        )

    return request


post = _create_method('post')
patch = _create_method('patch')
get = _create_method('get')

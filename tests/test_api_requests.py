import mock
import os
import requests
from requests.exceptions import HTTPError
import six
import sys
import unittest

import dash_auth.api_requests as api_requests

if (sys.version_info > (3, 0)):
    from io import StringIO as IO
else:
    from io import BytesIO as IO

try:
    from contextlib import redirect_stdout as captured_output
except ImportError:
    from .utils import captured_output


def plotly_query():
    """
    Simple query against plotly API this is mocked in tests
    """
    resp = api_requests.get('/v2/users/current')
    resp.raise_for_status()
    return resp


JSON_DATA = {'username': 'chris'}


def create_mock_response(
        status=200,
        raise_for_status=None):
    def mocked_get(*args, **kwargs):
        mock_resp = mock.Mock()
        # mock raise_for_status call w/optional error
        mock_resp.raise_for_status = mock.Mock()
        if raise_for_status:
            mock_resp.raise_for_status.side_effect = raise_for_status
        mock_resp.status_code = status
        mock_resp.json = mock.Mock(
            return_value=JSON_DATA
        )
        return mock_resp
    return mocked_get


class TestRequestsCall(unittest.TestCase):
    @mock.patch(
        'requests.get',
        side_effect=create_mock_response())
    def test_plotly_query(self, mock_get):
        result = plotly_query()
        self.assertEqual(result.json(), JSON_DATA)
        self.failUnless(result.raise_for_status.called)
        self.assertEqual(mock_get.call_count, 1)

    @mock.patch(
        'requests.get',
        side_effect=create_mock_response(
            status=500,
            raise_for_status=HTTPError("Gateway Timeout")
        ))
    def test_failed_query(self, mock_get):
        self.assertRaises(HTTPError, plotly_query)
        self.assertTrue(
            mock_get.call_count > 3,
            '''
            Mocked request should have been called > 3 times,
            instead it was called {} times'''.format(
                mock_get.call_count)
        )

    def test_request_logs(self):
        test_cases = [
            ['', [
                'Invalid URL',
                'No schema supplied',
                'gettaddrinfo failed',
                ['nodename nor servname provided, or not known',
                 'Name or service not known']
            ]],
            ['typo://plotly.acme.com', [
                'No connection adapters were found',
                'gettaddrinfo failed',
                ['nodename nor servname provided, or not known',
                 'No connection adapters were found']
            ]],
            ['https://doesntexist.plotly.systems', [
                'Failed to establish a new connection',
                'gettaddrinfo failed',
                ['nodename nor servname provided, or not known',
                 'Name or service not known']
            ]],
            ['https://expired.badssl.com', [
                'Caused by SSLError(SSLError("bad handshake: Error([(',
                'SSL routines',
                'tls_process_server_certificate',
                'certificate verify failed',
                'gettaddrinfo: ',
                "'104.154.89.105', 443"
            ]],
            ['https://self-signed.badssl.com', [
                'Caused by SSLError(SSLError("bad handshake: Error([(',
                'SSL routines',
                'tls_process_server_certificate',
                'certificate verify failed',
                'gettaddrinfo',
                "'104.154.89.105', 443"
            ]]
        ]

        for test_case in test_cases:
            url, expected_messages = test_case
            os.environ['plotly_api_domain'] = url
            f = IO()
            with captured_output(f) as out:
                try:
                    api_requests.post('/dash-apps')
                except Exception:
                    pass

            for expected_message in [url] + expected_messages:
                stdout = out.getvalue()
                if isinstance(expected_message, six.string_types):
                    self.assertTrue(
                        expected_message in stdout,
                        'Expected "{}" to be in:\n{}\n'.format(
                            expected_message, stdout)
                    )
                else:
                    self.assertTrue(
                        (expected_message[0] in stdout) or
                        (expected_message[1] in stdout),
                        'Expected\n"{}"\nor"{}"\nto be in:\n{}\n'.format(
                            expected_message[0], expected_message[1], stdout)
                    )

if __name__ == '__main__':
    unittest.main()

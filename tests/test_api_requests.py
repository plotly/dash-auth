import mock
import os
import requests
from requests.exceptions import HTTPError
import unittest

import dash_auth.api_requests as api_requests
from utils import captured_output

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
    def test_google_query(self, mock_get):
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
                'nodename nor servname provided, or not known'
            ]],
            ['typo://plotly.acme.com', [
                'No connection adapters were found',
                'gettaddrinfo failed',
                'nodename nor servname provided, or not known'
            ]],
            ['https://doesntexist.plotly.systems', [
                'Failed to establish a new connection',
                'gettaddrinfo failed',
                'nodename nor servname provided, or not known',
            ]],
            ['https://expired.badssl.com', [
                'Caused by SSLError(SSLError("bad handshake: Error([(',
                'SSL routines', 'tls_process_server_certificate',
                'certificate verify failed',
                ("gettaddrinfo: [(2, 2, 17, '', ('104.154.89.105', 443)), "
                 "(2, 1, 6, '', ('104.154.89.105', 443))]")
            ]],
            ['https://self-signed.badssl.com', [
                'Caused by SSLError(SSLError("bad handshake: Error([(',
                'SSL routines', 'tls_process_server_certificate',
                'certificate verify failed',
                ("gettaddrinfo: [(2, 2, 17, '', ('104.154.89.105', 443)), "
                 "(2, 1, 6, '', ('104.154.89.105', 443))]")
            ]]
        ]
        for test_case in test_cases:
            url, expected_messages = test_case
            os.environ['plotly_api_domain'] = url
            with captured_output() as (out, err):
                try:
                    api_requests.post('/dash-apps')
                except:
                    pass

            for expected_message in [url] + expected_messages:
                self.assertTrue(
                    expected_message in out.getvalue(),
                    'Expected "{}" to be in:\n{}\n'.format(
                        expected_message, out.getvalue())
                )

if __name__ == '__main__':
    unittest.main()

import mock
import requests
from requests.exceptions import HTTPError
import unittest

import dash_auth.api_requests as api_requests

def plotly_query():
    """
    Simple query against plotly API this is mocked in tests
    """
    resp = api_requests.get('https://plot.ly/v2/users/current')
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

if __name__ == '__main__':
    unittest.main()

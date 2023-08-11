from dash import Dash, Input, Output, dcc, html
import requests

from dash_auth import basic_auth, add_public_routes


TEST_USERS = {
    "valid": [
        ["hello", "world"],
        ["hello2", "wo:rld"]
    ],
    "invalid": [
        ["hello", "password"]
    ],
}


def test_ba001_basic_auth_login_flow(dash_br, dash_thread_server):
    app = Dash(__name__)
    app.layout = html.Div([
        dcc.Input(id="input", value="initial value"),
        html.Div(id="output")
    ])

    @app.callback(Output("output", "children"), Input("input", "value"))
    def update_output(new_value):
        return new_value

    basic_auth.BasicAuth(app, TEST_USERS["valid"], public_routes=["/home"])
    add_public_routes(app, ["/user/<user_id>/public"])

    dash_thread_server(app)
    base_url = dash_thread_server.url

    def test_failed_views(url):
        assert requests.get(url).status_code == 401

    def test_successful_views(url):
        assert requests.get(url.strip("/") + "/_dash-layout").status_code == 200
        assert requests.get(url.strip("/") + "/home").status_code == 200
        assert requests.get(url.strip("/") + "/user/john123/public").status_code == 200

    test_failed_views(base_url)
    test_successful_views(base_url)

    for user, password in TEST_USERS["invalid"]:
        test_failed_views(base_url.replace("//", f"//{user}:{password}@"))
        test_successful_views(base_url.replace("//", f"//{user}:{password}@"))

    # Test login for each user:
    for user, password in TEST_USERS["valid"]:
        # login using the URL instead of the alert popup
        # selenium has no way of accessing the alert popup
        dash_br.driver.get(base_url.replace("//", f"//{user}:{password}@"))

        # the username:password@host url doesn"t work right now for dash
        # routes, but it saves the credentials as part of the browser.
        # visiting the page again will use the saved credentials
        dash_br.driver.get(base_url)
        dash_br.wait_for_text_to_equal("#output", "initial value")

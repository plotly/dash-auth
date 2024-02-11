import os
from unittest.mock import patch

import requests
from dash import Dash, Input, Output, dcc, html
from flask import redirect

from dash_auth import (
    protected_callback,
    OIDCAuth,
)


def valid_authorize_redirect(_, redirect_uri, *args, **kwargs):
    return redirect("/" + redirect_uri.split("/", maxsplit=3)[-1])


def invalid_authorize_redirect(_, redirect_uri, *args, **kwargs):
    base_url = "/" + redirect_uri.split("/", maxsplit=3)[-1]
    return redirect(f"{base_url}?error=Unauthorized&error_description=something went wrong")


def valid_authorize_access_token(*args, **kwargs):
    return {
        "userinfo": {"email": "a.b@mail.com", "groups": ["viewer", "editor"]},
        "refresh_token": "ABCDEF",
    }


@patch("authlib.integrations.flask_client.apps.FlaskOAuth2App.authorize_redirect", valid_authorize_redirect)
@patch("authlib.integrations.flask_client.apps.FlaskOAuth2App.authorize_access_token", valid_authorize_access_token)
def test_oa001_oidc_auth_login_flow_success(dash_br, dash_thread_server):
    app = Dash(__name__)
    app.layout = html.Div([
        dcc.Input(id="input", value="initial value"),
        html.Div(id="output1"),
        html.Div(id="output2"),
        html.Div("static", id="output3"),
        html.Div("static", id="output4"),
        html.Div("not static", id="output5"),
    ])

    @app.callback(Output("output1", "children"), Input("input", "value"))
    def update_output1(new_value):
        return new_value

    @protected_callback(
        Output("output2", "children"),
        Input("input", "value"),
        groups=["editor"],
        check_type="one_of",
    )
    def update_output2(new_value):
        return new_value

    @protected_callback(
        Output("output3", "children"),
        Input("input", "value"),
        groups=["admin"],
        check_type="one_of",
    )
    def update_output3(new_value):
        return new_value

    @protected_callback(
        Output("output4", "children"),
        Input("input", "value"),
        groups=["viewer"],
        check_type="none_of",
    )
    def update_output4(new_value):
        return new_value

    @protected_callback(
        Output("output5", "children"),
        Input("input", "value"),
        groups=["viewer", "editor"],
        check_type="all_of",
    )
    def update_output5(new_value):
        return new_value

    oidc = OIDCAuth(app, secret_key="Test")
    oidc.register_provider(
        "oidc",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id>",
        client_secret="<client-secret>",
        server_metadata_url="https://idp.com/oidc/2/.well-known/openid-configuration",
    )
    dash_thread_server(app)
    base_url = dash_thread_server.url

    assert requests.get(base_url).status_code == 200

    dash_br.driver.get(base_url)
    dash_br.wait_for_text_to_equal("#output1", "initial value")
    dash_br.wait_for_text_to_equal("#output2", "initial value")
    dash_br.wait_for_text_to_equal("#output3", "static")
    dash_br.wait_for_text_to_equal("#output4", "static")
    dash_br.wait_for_text_to_equal("#output5", "initial value")


@patch("authlib.integrations.flask_client.apps.FlaskOAuth2App.authorize_redirect", invalid_authorize_redirect)
def test_oa002_oidc_auth_login_fail(dash_thread_server):
    app = Dash(__name__)
    app.layout = html.Div([
        dcc.Input(id="input", value="initial value"),
        html.Div(id="output")
    ])

    @app.callback(Output("output", "children"), Input("input", "value"))
    def update_output(new_value):
        return new_value

    oidc = OIDCAuth(app, public_routes=["/public"], secret_key="Test")
    oidc.register_provider(
        "oidc",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id>",
        client_secret="<client-secret>",
        server_metadata_url="https://idp.com/oidc/2/.well-known/openid-configuration",
    )
    dash_thread_server(app)
    base_url = dash_thread_server.url

    def test_unauthorized(url):
        r = requests.get(url)
        assert r.status_code == 401
        assert r.text == "Unauthorized: something went wrong"

    def test_authorized(url):
        assert requests.get(url).status_code == 200

    test_unauthorized(base_url)
    test_authorized(os.path.join(base_url, "public"))


@patch("authlib.integrations.flask_client.apps.FlaskOAuth2App.authorize_redirect", valid_authorize_redirect)
@patch("authlib.integrations.flask_client.apps.FlaskOAuth2App.authorize_access_token", valid_authorize_access_token)
def test_oa003_oidc_auth_login_several_idp(dash_br, dash_thread_server):
    app = Dash(__name__)
    app.layout = html.Div([
        dcc.Input(id="input", value="initial value"),
        html.Div(id="output1"),
    ])

    @app.callback(Output("output1", "children"), Input("input", "value"))
    def update_output1(new_value):
        return new_value

    oidc = OIDCAuth(app, secret_key="Test")
    # Add a first provider
    oidc.register_provider(
        "idp1",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id>",
        client_secret="<client-secret>",
        server_metadata_url="https://idp.com/oidc/2/.well-known/openid-configuration",
    )
    # Add a second provider
    oidc.register_provider(
        "idp2",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id2>",
        client_secret="<client-secret2>",
        server_metadata_url="https://idp2.com/oidc/2/.well-known/openid-configuration",
    )

    dash_thread_server(app)
    base_url = dash_thread_server.url

    assert requests.get(base_url).status_code == 400

    # Login with IDP1
    assert requests.get(os.path.join(base_url, "oidc/idp1/login")).status_code == 200

    # Logout
    assert requests.get(os.path.join(base_url, "oidc/logout")).status_code == 200

    assert requests.get(base_url).status_code == 400

    # Login with IDP2
    assert requests.get(os.path.join(base_url, "oidc/idp2/login")).status_code == 200

    dash_br.driver.get(os.path.join(base_url, "oidc/idp2/login"))
    dash_br.driver.get(base_url)
    dash_br.wait_for_text_to_equal("#output1", "initial value")

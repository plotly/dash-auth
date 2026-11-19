"""Gzip-compressed callback bodies pass the auth hook on every backend.

The renderer gzips large callback payloads when a callback sets
``compress_payload`` and Dash inflates them before dispatch. The auth hook used
to parse the raw bytes as JSON, see no body, and refuse even logged-in users.
"""

import asyncio
import base64
import gzip
import json
import uuid

import pytest
from dash import Dash, Input, Output, callback, html

from dash_auth_async import BasicAuth

pytest.importorskip("dash._compression", reason="dash without gzip payloads")

pytestmark = pytest.mark.usefixtures(
    "reset_active_backend", "isolated_callback_registry"
)

PATH = "/_dash-update-component"
BACKENDS = ["flask", "quart", "fastapi"]


def _headers(user):
    headers = {"Content-Type": "application/json", "Content-Encoding": "gzip"}
    if user is not None:
        token = base64.b64encode(f"{user}:{user}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    return headers


def _app(backend):
    if backend != "flask":
        pytest.importorskip(backend)
    tag = uuid.uuid4().hex
    btn, out = f"btn-{tag}", f"out-{tag}"
    app = Dash(__name__, backend=backend)
    app.layout = html.Div([html.Button(id=btn), html.Div(id=out)])

    @callback(
        Output(out, "children"), Input(btn, "n_clicks"), prevent_initial_call=True
    )
    def echo(n):
        return f"clicked {n}"

    BasicAuth(app, {"admin": "admin"}, secret_key="Test!")
    body = {
        "output": f"{out}.children",
        "outputs": {"id": out, "property": "children"},
        "inputs": [{"id": btn, "property": "n_clicks", "value": 3}],
        "changedPropIds": [f"{btn}.n_clicks"],
        "state": [],
    }
    return app, out, gzip.compress(json.dumps(body).encode())


def _post(backend, user):
    """POST one gzipped callback request.

    Returns:
        ``(status_code, response_text, output_id)``.
    """
    app, out, data = _app(backend)
    if backend == "flask":
        client = app.server.test_client()
        client.get("/", headers=_headers("admin"))  # Dash's first-request setup
        resp = client.post(PATH, data=data, headers=_headers(user))
        return resp.status_code, resp.get_data(as_text=True), out
    if backend == "quart":

        async def run():
            client = app.server.test_client()
            await client.get("/", headers=_headers("admin"))
            resp = await client.post(PATH, data=data, headers=_headers(user))
            return resp.status_code, await resp.get_data(as_text=True)

        status, text = asyncio.run(run())
        return status, text, out
    from fastapi.testclient import TestClient

    with TestClient(app.server) as client:
        client.get("/", headers=_headers("admin"))
        resp = client.post(PATH, content=data, headers=_headers(user))
        return resp.status_code, resp.text, out


@pytest.mark.parametrize("backend", BACKENDS)
def test_cb001_logged_in_user_can_send_compressed_callback(backend):
    """RED before fix: the hook parsed the gzip bytes as JSON and answered 401."""
    status, text, out = _post(backend, "admin")
    assert status == 200
    assert json.loads(text)["response"][out]["children"] == "clicked 3"


@pytest.mark.parametrize("backend", BACKENDS)
def test_cb002_anonymous_compressed_callback_still_denied(backend):
    status, _text, _out = _post(backend, None)
    assert status == 401

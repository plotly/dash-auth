"""A protected stream stops once its session logs out, on every backend.

Real server, raw HTTP: one client reads a slow protected NDJSON stream; the
same browser (same cookies) logs out mid-stream, as a second tab would. The
stream must end with the unauthenticated fallback instead of running on.
"""

import json
import threading
import time
import uuid

import dash
import pytest
from dash import Dash, Input, Output, html
from packaging.version import Version

from dash_auth_async import OIDCAuth, protected_callback
from dash_auth_async.stream_revocation import ensure_session_id

requests = pytest.importorskip("requests", reason="requests is not installed")

pytestmark = [
    pytest.mark.skipif(
        Version(dash.__version__) < Version("4.5.0"),
        reason="streaming callbacks need dash>=4.5.0",
    ),
    pytest.mark.usefixtures("reset_active_backend", "isolated_callback_registry"),
]

TIMEOUT = 15
CHUNKS = 40


async def _slow_agen(_n):
    import asyncio

    for i in range(CHUNKS):
        yield f"chunk-{i}"
        await asyncio.sleep(0.2)


def _serve(dash_thread_server, backend, **callback_kwargs):
    """Start an OIDC-protected app with a slow protected stream.

    Returns:
        ``(base_url, output_id, callback_body)``.
    """
    if backend != "flask":
        pytest.importorskip(backend)
    from dash import LocalSharedStorage  # dash>=4.5 only

    tag = uuid.uuid4().hex
    btn, out = f"btn-{tag}", f"out-{tag}"
    # Dash serves HTTP streams only with shared storage.
    app = Dash(
        __name__,
        backend=backend,
        shared_storage=LocalSharedStorage(namespace=uuid.uuid4().hex),
    )
    app.layout = html.Div([html.Button(id=btn), html.Div(id=out)])
    protected_callback(
        Output(out, "children"),
        Input(btn, "n_clicks"),
        unauthenticated_output="logged-out",
        prevent_initial_call=True,
        **callback_kwargs,
    )(_slow_agen)
    auth = OIDCAuth(app, secret_key="Test!", public_routes=["/test-login"])

    # Test-only login: puts a user in the session as the OIDC callback would,
    # without an IdP round-trip, the same way on every backend.
    def login():
        auth.session["user"] = {"email": "a@b.c", "groups": []}
        ensure_session_id(auth.session)
        return "ok"

    async def alogin():
        return auth.backend.coerce_response(login())

    view = alogin if auth.backend.is_async else login
    auth.backend.add_route(app.server, "/test-login", view, "test_login", ["GET"])
    dash_thread_server(app)
    body = {
        "output": f"{out}.children",
        "outputs": {"id": out, "property": "children"},
        "inputs": [{"id": btn, "property": "n_clicks", "value": 1}],
        "changedPropIds": [f"{btn}.n_clicks"],
        "state": [],
    }
    return dash_thread_server.url.rstrip("/"), out, body


@pytest.mark.parametrize("backend", ["flask", "quart", "fastapi"])
def test_slo011_logout_stops_an_open_protected_stream(dash_thread_server, backend):
    """RED before fix: the stream ran to its last chunk after logout."""
    base, out, body = _serve(dash_thread_server, backend)
    browser = requests.Session()
    assert browser.get(base + "/test-login", timeout=TIMEOUT).status_code == 200

    frames = []
    first_chunk = threading.Event()

    def read_stream():
        with browser.post(
            base + "/_dash-update-component", json=body, stream=True, timeout=TIMEOUT
        ) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.strip():
                    frames.append(json.loads(line))
                    first_chunk.set()

    reader = threading.Thread(target=read_stream, daemon=True)
    reader.start()
    assert first_chunk.wait(TIMEOUT)

    # A second tab of the same browser: same cookies, separate request.
    logout_at = time.monotonic()
    assert browser.get(base + "/oidc/logout", timeout=TIMEOUT).status_code == 200
    reader.join(TIMEOUT)
    assert not reader.is_alive()

    children = [f["response"][out]["children"] for f in frames if "response" in f]
    assert children[-1] == "logged-out"
    assert len(children) < CHUNKS  # stopped early, not run to completion
    assert time.monotonic() - logout_at < 5
    assert frames[-1] == {"done": True}


@pytest.mark.parametrize("backend", ["quart", "fastapi"])
def test_slo013_logout_ends_a_websocket_stream(dash_thread_server, backend):
    """Over a WebSocket no session id is captured: the stream must end because
    logout closes that browser's authenticated socket (close_authenticated_ws)."""
    websocket = pytest.importorskip("websocket", reason="websocket-client missing")
    base, _out, body = _serve(dash_thread_server, backend, websocket=True)
    browser = requests.Session()
    assert browser.get(base + "/test-login", timeout=TIMEOUT).status_code == 200
    assert browser.get(base + "/", timeout=TIMEOUT).status_code == 200  # dac_client
    cookie = "; ".join(f"{c.name}={c.value}" for c in browser.cookies)

    conn = websocket.create_connection(
        base.replace("http://", "ws://") + "/_dash-ws-callback",
        header=[f"Cookie: {cookie}"],
        origin=base,
        timeout=TIMEOUT,
    )
    received = ""
    try:
        conn.send(
            json.dumps(
                {
                    "type": "callback_request",
                    "requestId": "1",
                    "rendererId": "r1",
                    "payload": body,
                }
            )
        )
        while "chunk-0" not in received:
            received += str(conn.recv())

        logout_at = time.monotonic()
        assert browser.get(base + "/oidc/logout", timeout=TIMEOUT).status_code == 200
        with pytest.raises(websocket.WebSocketException):
            while True:
                received += str(conn.recv())
        assert time.monotonic() - logout_at < 5
    finally:
        conn.close()

    assert f"chunk-{CHUNKS - 1}" not in received

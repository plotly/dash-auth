"""Streaming callbacks behind auth on every backend, over a real server.

Drives raw HTTP with ``requests`` (no browser) the way the renderer does: an
inline NDJSON stream, and the multiplexed path (uplink with
``streamConnection``, then the ``streamDownlink`` read). A real server matters
here: Quart and FastAPI hold the downlink open for the page's life, and FastAPI
streams pass through our ASGI auth middleware.
"""

import base64
import json
import re
import threading
import time
import uuid

import dash
import pytest
from dash import Dash, Input, Output, html
from packaging.version import Version

from dash_auth_async import BasicAuth, protected_callback, public_callback

requests = pytest.importorskip("requests", reason="requests is not installed")

pytestmark = [
    pytest.mark.skipif(
        Version(dash.__version__) < Version("4.5.0"),
        reason="streaming callbacks need dash>=4.5.0",
    ),
    pytest.mark.usefixtures("reset_active_backend", "isolated_callback_registry"),
]

BACKENDS = ["flask", "quart", "fastapi"]
USERS = {"admin": "admin", "guest": "guest"}
PATH = "/_dash-update-component"
TIMEOUT = 15


def _fresh_storage(storage_cls):
    """A shared storage with its own owner election.

    Every default ``LocalSharedStorage`` in a process shares one owner address
    (a socket file on POSIX). Here that owner belongs to whichever test's app
    started first; once that test's server stops, later tests time out on it.
    """
    return storage_cls(namespace=uuid.uuid4().hex)


def _headers(user):
    if user is None:
        return {}
    token = base64.b64encode(f"{user}:{user}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def _agen(_n):
    yield "chunk-1"
    yield "chunk-2"


def _serve(dash_thread_server, backend, decorator, **kwargs):
    """Start a real server with one streaming callback.

    Returns:
        ``(base_url, output_id, callback_body)``.
    """
    from dash import LocalSharedStorage  # dash>=4.5 only

    if backend != "flask":
        pytest.importorskip(backend)
    tag = uuid.uuid4().hex
    btn, out = f"btn-{tag}", f"out-{tag}"
    app = Dash(
        __name__, backend=backend, shared_storage=_fresh_storage(LocalSharedStorage)
    )
    app.layout = html.Div([html.Button(id=btn), html.Div(id=out)])
    decorator(
        Output(out, "children"),
        Input(btn, "n_clicks"),
        prevent_initial_call=True,
        **kwargs,
    )(_agen)
    BasicAuth(
        app,
        USERS,
        user_groups={"admin": ["admin"]},
        public_routes=["/"],
        secret_key="Test!",
    )
    dash_thread_server(app)
    body = {
        "output": f"{out}.children",
        "outputs": {"id": out, "property": "children"},
        "inputs": [{"id": btn, "property": "n_clicks", "value": 1}],
        "changedPropIds": [f"{btn}.n_clicks"],
        "state": [],
    }
    return dash_thread_server.url.rstrip("/"), out, body


def _end_token(base, user):
    page = requests.get(base + "/", headers=_headers(user), timeout=TIMEOUT)
    assert page.status_code == 200
    match = re.search(r'"end_id":\s*"([^"]+)"', page.text)
    assert match is not None
    return match[1]


def _children(frames, out):
    return [f["response"][out]["children"] for f in frames if "response" in f]


@pytest.mark.parametrize("backend", BACKENDS)
def test_sb001_authorised_user_streams_every_chunk(dash_thread_server, backend):
    base, out, body = _serve(
        dash_thread_server, backend, protected_callback, groups=["admin"]
    )
    resp = requests.post(
        base + PATH, json=body, headers=_headers("admin"), timeout=TIMEOUT
    )
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("application/x-ndjson")
    frames = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert _children(frames, out) == ["chunk-1", "chunk-2"]
    assert frames[-1] == {"done": True}


@pytest.mark.parametrize("backend", BACKENDS)
def test_sb002_denied_user_gets_fallback_as_stream_frame(dash_thread_server, backend):
    base, out, body = _serve(
        dash_thread_server,
        backend,
        protected_callback,
        groups=["admin"],
        missing_permissions_output="forbidden",
    )
    resp = requests.post(
        base + PATH, json=body, headers=_headers("guest"), timeout=TIMEOUT
    )
    assert resp.status_code == 200
    frames = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert _children(frames, out) == ["forbidden"]
    assert frames[-1] == {"done": True}


@pytest.mark.parametrize("backend", BACKENDS)
def test_sb003_anonymous_page_reads_public_stream_via_downlink(
    dash_thread_server, backend
):
    base, _out, body = _serve(dash_thread_server, backend, public_callback)
    url = f"{base}{PATH}?endId={_end_token(base, None)}"

    # Like the renderer: open the downlink first, then start the stream. Flask
    # answers each downlink poll at once (so keep polling); Quart/FastAPI hold
    # one open for the page's life and push frames as they are published.
    received = []

    def read_downlink():
        deadline = time.monotonic() + TIMEOUT
        while "chunk-2" not in "".join(received) and time.monotonic() < deadline:
            with requests.post(
                url,
                json={"streamDownlink": {"from": None}},
                stream=True,
                timeout=TIMEOUT,
            ) as downlink:
                received.append(f"status={downlink.status_code}")
                for line in downlink.iter_lines():
                    received.append(line.decode())
                    if "chunk-2" in line.decode():
                        return
            time.sleep(0.1)

    reader = threading.Thread(target=read_downlink, daemon=True)
    reader.start()
    time.sleep(0.5)  # let the downlink attach before frames are published
    uplink = requests.post(
        url, json={**body, "streamConnection": {"requestId": "r1"}}, timeout=TIMEOUT
    )
    assert uplink.status_code == 200
    assert uplink.json() == {"multi": True, "stream": True}
    reader.join(TIMEOUT + 5)

    received = "".join(received)
    assert "status=401" not in received
    assert "chunk-1" in received
    assert "chunk-2" in received


@pytest.mark.parametrize("backend", BACKENDS)
def test_sb004_anonymous_uplink_to_protected_stream_denied(dash_thread_server, backend):
    base, _out, body = _serve(
        dash_thread_server, backend, protected_callback, groups=["admin"]
    )
    url = f"{base}{PATH}?endId={_end_token(base, None)}"
    resp = requests.post(
        url, json={**body, "streamConnection": {"requestId": "r1"}}, timeout=TIMEOUT
    )
    assert resp.status_code == 401

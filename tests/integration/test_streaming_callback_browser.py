"""Streaming callbacks behind auth, rendered by a real browser on every backend.

The raw-HTTP siblings in ``test_streaming_callback_backends.py`` pin *where* a
failure is; these prove the renderer actually shows it. With shared storage the
renderer multiplexes: it opens the ``streamDownlink`` and starts each stream
with a ``streamConnection`` uplink -- the exact traffic that used to get a 401
for anonymous pages, and a cut-off stream on FastAPI.
"""

import asyncio
import uuid

import dash
import pytest
from dash import Dash, Input, Output, html
from packaging.version import Version

from dash_auth_async import BasicAuth, protected_callback, public_callback

pytestmark = [
    pytest.mark.skipif(
        Version(dash.__version__) < Version("4.5.0"),
        reason="streaming callbacks need dash>=4.5.0",
    ),
    pytest.mark.usefixtures("reset_active_backend", "isolated_callback_registry"),
]

BACKENDS = ["flask", "quart", "fastapi"]
USERS = {"admin": "admin", "guest": "guest"}


def _fresh_storage(storage_cls):
    """A shared storage with its own owner election.

    Every default ``LocalSharedStorage`` in a process shares one owner address
    (a socket file on POSIX). Here that owner belongs to whichever test's app
    started first; once that test's server stops, later tests time out on it.
    """
    return storage_cls(namespace=uuid.uuid4().hex)


def _serve(dash_thread_server, backend, decorator, *, public_page=False, **kwargs):
    """Serve a page whose streaming callback fires on load.

    Returns:
        ``(base_url, output_selector)``.
    """
    from dash import LocalSharedStorage  # dash>=4.5 only

    if backend != "flask":
        pytest.importorskip(backend)
    out = f"out-{uuid.uuid4().hex}"
    app = Dash(
        __name__, backend=backend, shared_storage=_fresh_storage(LocalSharedStorage)
    )
    app.layout = html.Div([html.Button(id=f"{out}-btn"), html.Div(id=out)])

    @decorator(Output(out, "children"), Input(f"{out}-btn", "n_clicks"), **kwargs)
    async def stream(_n):
        yield "chunk-1"
        await asyncio.sleep(0.3)  # chunk-2 can only appear if the stream stays open
        yield "chunk-2"

    BasicAuth(
        app,
        USERS,
        user_groups={"admin": ["admin"]},
        # Logged-in tests need "/" private: the browser only sends the seeded
        # basic-auth credentials after a 401 challenge.
        public_routes=["/"] if public_page else None,
        secret_key="Test!",
    )
    dash_thread_server(app)
    return dash_thread_server.url, f"#{out}"


def _open_as(dash_br, base_url, user):
    if user is not None:
        # Seed saved credentials, then load the page plainly.
        dash_br.driver.get(base_url.replace("//", f"//{user}:{user}@"))
    dash_br.driver.get(base_url)


@pytest.mark.parametrize("backend", BACKENDS)
def test_sbr001_anonymous_page_renders_public_stream(
    dash_br, dash_thread_server, backend
):
    base_url, out = _serve(
        dash_thread_server, backend, public_callback, public_page=True
    )
    _open_as(dash_br, base_url, None)
    dash_br.wait_for_text_to_equal(out, "chunk-2")


@pytest.mark.parametrize("backend", BACKENDS)
def test_sbr002_admin_renders_protected_stream(dash_br, dash_thread_server, backend):
    base_url, out = _serve(
        dash_thread_server, backend, protected_callback, groups=["admin"]
    )
    _open_as(dash_br, base_url, "admin")
    dash_br.wait_for_text_to_equal(out, "chunk-2")


@pytest.mark.parametrize("backend", BACKENDS)
def test_sbr003_guest_renders_fallback_for_protected_stream(
    dash_br, dash_thread_server, backend
):
    base_url, out = _serve(
        dash_thread_server,
        backend,
        protected_callback,
        groups=["admin"],
        missing_permissions_output="forbidden",
    )
    _open_as(dash_br, base_url, "guest")
    dash_br.wait_for_text_to_equal(out, "forbidden")


@pytest.mark.parametrize("backend", ["quart", "fastapi"])
@pytest.mark.parametrize(
    ("user", "expected"), [("admin", "chunk-2"), ("guest", "forbidden")]
)
def test_sbr004_protected_stream_over_websocket(
    dash_br, dash_thread_server, backend, user, expected
):
    """Over WS the user comes from the socket's session, captured at dispatch."""
    base_url, out = _serve(
        dash_thread_server,
        backend,
        protected_callback,
        groups=["admin"],
        missing_permissions_output="forbidden",
        websocket=True,
    )
    _open_as(dash_br, base_url, user)
    dash_br.wait_for_text_to_equal(out, expected)

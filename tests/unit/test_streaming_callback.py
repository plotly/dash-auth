"""Streaming (async-generator) callbacks through dash-auth-async decorators.

Dash 4.5 added streaming callbacks: it picks the streaming dispatch path at
registration via ``inspect.isasyncgenfunction``. These tests exercise Dash's own
streaming machinery, so they only run where it exists. The wrapper-level kind
checks (gp011-gp017 in ``test_protected_callback_async.py``) test our code alone
and run on every Dash version.
"""

import base64
import json
import uuid

import dash
import pytest
from dash import Dash, Input, Output, html
from dash._callback import GLOBAL_CALLBACK_MAP
from packaging.version import Version

from dash_auth_async import BasicAuth, protected, protected_callback, public_callback

pytestmark = [
    pytest.mark.skipif(
        Version(dash.__version__) < Version("4.5.0"),
        reason="streaming callbacks need dash>=4.5.0",
    ),
    pytest.mark.usefixtures(
        "reset_active_backend", "isolated_callback_registry", "streams_not_shut_down"
    ),
]

USERS = {"admin": "admin", "guest": "guest"}


@pytest.fixture
def streams_not_shut_down():
    """Clear Dash's process-global stream shutdown flag.

    Any earlier test whose Quart/FastAPI app shut down set it (via
    ``shutdown_active_streams``); only a real server start clears it, which a
    Flask test client never does -- every stream would then end empty.
    """
    from dash._streaming import _shutdown

    _shutdown.clear()


def _fresh_storage(storage_cls):
    """A shared storage with its own owner election.

    Every default ``LocalSharedStorage`` in a process shares one owner address
    (a socket file on POSIX). Here that owner belongs to whichever test's app
    started first; once that test's server stops, later tests time out on it.
    """
    return storage_cls(namespace=uuid.uuid4().hex)


def _ids():
    # Unique ids: callbacks register into Dash's process-global map.
    tag = uuid.uuid4().hex
    return f"btn-{tag}", f"out-{tag}"


def _register(decorator, btn, out, target, **kwargs):
    decorator(
        Output(out, "children"),
        Input(btn, "n_clicks"),
        prevent_initial_call=True,
        **kwargs,
    )(target)


async def _agen(_n):
    yield "chunk-1"
    yield "chunk-2"


@pytest.mark.parametrize(
    ("decorator", "kwargs"),
    [(public_callback, {}), (protected_callback, {"groups": ["admin"]})],
)
def test_st001_async_generator_registers_as_dash_stream(decorator, kwargs):
    """RED before fix: protected_callback registered a plain def, not a stream."""
    btn, out = _ids()
    Dash(__name__)  # public_callback needs an instantiated app
    _register(decorator, btn, out, _agen, **kwargs)
    assert GLOBAL_CALLBACK_MAP[f"{out}.children"].get("stream") is True


def test_st002_sync_generator_rejected_at_registration():
    """protected() keeps the sync-generator kind, so Dash's own error surfaces."""

    def gen(_n):
        yield "x"

    btn, out = _ids()
    with pytest.raises(dash.exceptions.StreamCallbackError):
        _register(protected_callback, btn, out, gen, groups=["admin"])


def _headers(user):
    token = base64.b64encode(f"{user}:{user}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _post_stream(user, *, direct=False):
    """POST one stream request on Flask to a group-protected streaming callback.

    ``direct`` stacks ``dash.callback`` on ``protected()`` instead of using
    ``protected_callback``.

    Returns:
        ``(response, output_id)``.
    """
    from dash import LocalSharedStorage  # dash>=4.5 only; module must import on older

    btn, out = _ids()
    app = Dash(__name__, shared_storage=_fresh_storage(LocalSharedStorage))
    BasicAuth(app, USERS, user_groups={"admin": ["admin"]}, secret_key="Test!")
    app.layout = html.Div([html.Button(id=btn), html.Div(id=out)])
    if direct:
        gated = protected(
            "login", groups=["admin"], missing_permissions_output="forbidden"
        )(_agen)
        _register(dash.callback, btn, out, gated)
    else:
        _register(
            protected_callback,
            btn,
            out,
            _agen,
            groups=["admin"],
            missing_permissions_output="forbidden",
        )

    client = app.server.test_client()
    client.get("/", headers=_headers(user))  # runs Dash's _setup_server
    resp = client.post(
        "/_dash-update-component",
        json={
            "output": f"{out}.children",
            "outputs": {"id": out, "property": "children"},
            "inputs": [{"id": btn, "property": "n_clicks", "value": 1}],
            "changedPropIds": [f"{btn}.n_clicks"],
            "state": [],
        },
        headers=_headers(user),
    )
    return resp, out


@pytest.mark.parametrize(
    "direct", [False, True], ids=["protected_callback", "protected"]
)
def test_st003_authorised_user_receives_every_chunk_over_http(direct):
    """RED before fix: Flask consumes the stream off-request, so the in-generator
    gate saw no user and denied even admins. ``protected`` used directly (under a
    plain ``dash.callback``) needs the same dispatch-time user capture."""
    resp, out = _post_stream("admin", direct=direct)

    assert resp.status_code == 200
    assert resp.mimetype == "application/x-ndjson"
    frames = [
        json.loads(line) for line in resp.get_data(as_text=True).splitlines() if line
    ]
    assert frames[-1] == {"done": True}
    assert [f["response"][out]["children"] for f in frames[:-1]] == [
        "chunk-1",
        "chunk-2",
    ]


def test_st004_denied_user_gets_fallback_as_stream_frame():
    """The fallback must travel as a stream frame: a multiplexed renderer ignores
    the uplink's body and only reads frames, so a plain JSON reply never shows."""
    resp, out = _post_stream("guest")

    assert resp.status_code == 200
    assert resp.mimetype == "application/x-ndjson"
    frames = [
        json.loads(line) for line in resp.get_data(as_text=True).splitlines() if line
    ]
    assert frames == [
        {"multi": True, "response": {out: {"children": "forbidden"}}},
        {"done": True},
    ]


@pytest.mark.parametrize(
    ("dispatch_user", "expected"),
    [
        ({"groups": ["admin"]}, ["chunk-1", "chunk-2"]),
        ({"groups": ["guest"]}, ["forbidden"]),
    ],
)
def test_st005_stream_gated_with_user_captured_at_dispatch(dispatch_user, expected):
    """The gate reads the user Dash's custom_data hook captured at dispatch, not
    the (absent) request context of wherever the stream is consumed."""
    import asyncio

    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    from dash_auth_async.group_protection import _USER_NAMESPACE

    btn, out = _ids()
    app = Dash(__name__)
    BasicAuth(app, USERS, user_groups={"admin": ["admin"]}, secret_key="Test!")
    stream = protected_callback(
        Output(out, "children"),
        Input(btn, "n_clicks"),
        groups=["admin"],
        missing_permissions_output="forbidden",
        prevent_initial_call=True,
    )(_agen)

    async def drain():
        # What Dash sets around each stream step: ctx with custom_data from
        # the hooks it ran at dispatch -- and no request context.
        captured = AttributeDict({_USER_NAMESPACE: dispatch_user})
        context_value.set(AttributeDict(custom_data=captured))
        return [chunk async for chunk in stream(1)]

    assert asyncio.run(drain()) == expected


def test_st006_stream_allowed_over_websocket():
    """Unlike background callbacks, streams may run over WS (gated in-stream)."""
    btn, out = _ids()
    app = Dash(__name__)
    auth = BasicAuth(app, USERS, user_groups={"admin": ["admin"]}, secret_key="Test!")
    _register(protected_callback, btn, out, _agen, groups=["admin"])
    assert auth.authorize_ws({"output": f"{out}.children"}, {"groups": []}) is True


def _anonymous_multiplex_app(decorator, **kwargs):
    """A page served anonymously (public ``/``) with one streaming callback.

    Returns:
        ``(client, end_token, body)`` -- a Flask test client that has loaded the
        page, the page's signed ``endId``, and the stream's uplink body.
    """
    import re

    from dash import LocalSharedStorage

    btn, out = _ids()
    app = Dash(__name__, shared_storage=_fresh_storage(LocalSharedStorage))
    BasicAuth(app, USERS, public_routes=["/"], secret_key="Test!")
    app.layout = html.Div([html.Button(id=btn), html.Div(id=out)])
    _register(decorator, btn, out, _agen, **kwargs)

    client = app.server.test_client()
    page = client.get("/")
    assert page.status_code == 200
    match = re.search(r'"end_id":\s*"([^"]+)"', page.get_data(as_text=True))
    assert match is not None
    end_token = match[1]
    body = {
        "output": f"{out}.children",
        "outputs": {"id": out, "property": "children"},
        "inputs": [{"id": btn, "property": "n_clicks", "value": 1}],
        "changedPropIds": [f"{btn}.n_clicks"],
        "state": [],
        "streamConnection": {"requestId": "r1"},
    }
    return client, end_token, body


def test_st007_anonymous_page_reads_public_stream_via_downlink():
    """RED before fix: the downlink poll has no ``output``, so it got a 401."""
    import time

    client, end_token, body = _anonymous_multiplex_app(public_callback)
    url = f"/_dash-update-component?endId={end_token}"

    uplink = client.post(url, json=body)
    assert uplink.status_code == 200
    assert uplink.get_json() == {"multi": True, "stream": True}

    received = ""
    deadline = time.monotonic() + 10  # the pump runs on Dash's own loop thread
    while "chunk-2" not in received and time.monotonic() < deadline:
        downlink = client.post(url, json={"streamDownlink": {"from": None}})
        assert downlink.status_code == 200
        received += downlink.get_data(as_text=True)
        time.sleep(0.05)
    assert "chunk-1" in received
    assert "chunk-2" in received

    cancel = client.post(url, json={"streamCancel": {"requestId": "r1"}})
    assert cancel.status_code == 200


def test_st008_downlink_still_bound_to_signed_page_token():
    """Passing the downlink through auth leaves Dash's per-page check in charge."""
    client, _end_token, _body = _anonymous_multiplex_app(public_callback)

    for body in (
        {"streamDownlink": {"from": None}},
        {"streamCancel": {"requestId": "x"}},
    ):
        assert client.post("/_dash-update-component", json=body).status_code == 403
        forged = "/_dash-update-component?endId=forged"
        assert client.post(forged, json=body).status_code == 403


def test_st009_anonymous_uplink_to_protected_stream_still_denied():
    """Only uplinks that pass auth publish to a page's downlink topic."""
    client, end_token, body = _anonymous_multiplex_app(
        protected_callback, groups=["admin"]
    )
    resp = client.post(f"/_dash-update-component?endId={end_token}", json=body)
    assert resp.status_code == 401


def test_st010_closing_the_stream_closes_the_user_generator():
    """Dash closes a cancelled/disconnected stream; the user's own generator must
    close with it (its cleanup runs now, not whenever the GC gets to it)."""
    import asyncio
    import contextvars

    cleaned_up = []

    async def agen(_n):
        try:
            yield "chunk-1"
            yield "chunk-2"
        finally:
            cleaned_up.append(True)

    stream = protected("login", groups=["admin"])(agen)

    async def first_chunk_then_close():
        from dash_auth_async.websocket_auth import _WS_AUTH_USER

        _WS_AUTH_USER.set({"groups": ["admin"]})
        gen = stream(1)
        assert await anext(gen) == "chunk-1"
        await gen.aclose()
        return list(cleaned_up)

    # Empty context: earlier Flask test-client dispatches leave a Dash ctx set on
    # this thread, which the stream would adopt as its dispatch user.
    result = contextvars.Context().run(asyncio.run, first_chunk_then_close())
    assert result == [True]


@pytest.mark.parametrize(
    "transport",
    [
        {"streamDownlink": None},
        {"streamCancel": None},
        {"streamDownlink": {"from": None}, "output": "OUT"},
    ],
    ids=["null-downlink", "null-cancel", "downlink-with-output"],
)
def test_st011_only_real_stream_transport_skips_auth(transport):
    """A null downlink/cancel is not stream transport to Dash (it dispatches it as
    a callback), and a body naming an output is a callback -- neither may skip auth."""
    client, end_token, body = _anonymous_multiplex_app(
        protected_callback, groups=["admin"]
    )
    if transport.get("output") == "OUT":
        transport = {**body, **transport, "output": body["output"]}
    resp = client.post(f"/_dash-update-component?endId={end_token}", json=transport)
    assert resp.status_code == 401

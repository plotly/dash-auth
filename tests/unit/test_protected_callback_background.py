"""``protected_callback(..., background=True)`` gates at HTTP dispatch.

A background job runs in a separate process with no request/session, so a group
gate *inside* the job always saw "no user" and denied everyone (the poll then
returned 204 forever). The gate now runs in ``Auth._authorize`` on the start
request and every poll; the job is registered unwrapped.

These tests drive a real ``DiskcacheManager`` job process on purpose: running the
job in-process (or in a thread) inherits the request context and would pass
against the unfixed code, so it would not pin the trigger.
"""

import asyncio
import base64
import json
import time
import uuid

import pytest

pytest.importorskip("diskcache", reason="dash[diskcache] is not installed")

import diskcache
from dash import ALL, Dash, DiskcacheManager, Input, Output, html
from dash._utils import create_callback_id, stringify_id

from dash_auth_async import BasicAuth, protected_callback

pytestmark = pytest.mark.usefixtures("reset_active_backend")

BACKENDS = ["flask", "quart", "fastapi"]
USERS = {"admin": "admin", "guest": "guest"}
JOB_TIMEOUT = 60  # a spawned job re-imports dash; slow on Windows


def _headers(user):
    if user is None:
        return {}
    token = base64.b64encode(f"{user}:{user}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _app(backend, cache_dir, **protect_kwargs):
    """Build a BasicAuth app with one group-protected background callback.

    Returns:
        ``(app, body)`` -- the app and the callback request body for it.
    """
    if backend != "flask":
        pytest.importorskip(backend)
    app = Dash(__name__, backend=backend)
    BasicAuth(app, USERS, user_groups={"admin": ["admin"]}, secret_key="Test!")
    # Unique ids: callbacks register into Dash's process-global map.
    btn, out = f"btn-{uuid.uuid4().hex}", f"out-{uuid.uuid4().hex}"
    app.layout = html.Div([html.Button(id=btn), html.Div(id=out)])

    @protected_callback(
        Output(out, "children"),
        Input(btn, "n_clicks"),
        groups=["admin"],
        background=True,
        manager=DiskcacheManager(diskcache.Cache(str(cache_dir))),
        prevent_initial_call=True,
        **protect_kwargs,
    )
    def job(_n):
        return "ran"

    body = {
        "output": f"{out}.children",
        "outputs": {"id": out, "property": "children"},
        "inputs": [{"id": btn, "property": "n_clicks", "value": 1}],
        "changedPropIds": [f"{btn}.n_clicks"],
        "state": [],
    }
    return app, body


def _poll_until_done(post, body, user, start):
    """Start the job, then poll like the renderer until it answers.

    Returns:
        ``(start_status, start_json, final_status, final_json)``.
    """
    status, data = start
    if status != 200 or "cacheKey" not in data:
        return status, data, status, data
    query = f"?cacheKey={data['cacheKey']}&job={data['job']}"
    deadline = time.monotonic() + JOB_TIMEOUT
    while time.monotonic() < deadline:
        p_status, p_data = post(body, user, query)
        if p_status != 200 or "response" in p_data:
            return status, data, p_status, p_data
        time.sleep(0.5)
    raise AssertionError("background job never produced a result")


def _run(backend, app, body, user):
    """Drive start + polls through the backend's own test client.

    Returns:
        ``(start_status, start_json, final_status, final_json)``.
    """
    path = "/_dash-update-component"

    def parse(status, text):
        return status, (json.loads(text) if status == 200 and text else {})

    if backend == "flask":
        client = app.server.test_client()

        def post(b, u, q=""):
            r = client.post(path + q, json=b, headers=_headers(u))
            return parse(r.status_code, r.text)

        return _poll_until_done(post, body, user, post(body, user))

    if backend == "fastapi":
        from starlette.testclient import TestClient

        with TestClient(app.server) as client:

            def post(b, u, q=""):
                r = client.post(path + q, json=b, headers=_headers(u))
                return parse(r.status_code, r.text)

            return _poll_until_done(post, body, user, post(body, user))

    async def run():
        client = app.server.test_client()

        async def apost(b, u, q=""):
            r = await client.post(path + q, json=b, headers=_headers(u))
            return parse(r.status_code, await r.get_data(as_text=True))

        start = await apost(body, user)
        status, data = start
        if status != 200 or "cacheKey" not in data:
            return status, data, status, data
        query = f"?cacheKey={data['cacheKey']}&job={data['job']}"
        deadline = time.monotonic() + JOB_TIMEOUT
        while time.monotonic() < deadline:
            p_status, p_data = await apost(body, user, query)
            if p_status != 200 or "response" in p_data:
                return status, data, p_status, p_data
            await asyncio.sleep(0.5)
        raise AssertionError("background job never produced a result")

    return asyncio.run(run())


def _children(data):
    (props,) = data["response"].values()
    return props["children"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_pcb001_group_member_job_runs(backend, tmp_path):
    """The trigger: an authorised admin's background job must actually run."""
    app, body = _app(backend, tmp_path, missing_permissions_output="denied")
    start_status, start, status, final = _run(backend, app, body, "admin")
    assert start_status == 200
    assert "cacheKey" in start  # a job was spawned
    assert status == 200
    assert _children(final) == "ran"


@pytest.mark.parametrize("backend", BACKENDS)
def test_pcb002_non_member_gets_fallback_and_no_job(backend, tmp_path):
    app, body = _app(backend, tmp_path, missing_permissions_output="denied")
    start_status, start, _, _ = _run(backend, app, body, "guest")
    assert start_status == 200
    assert "cacheKey" not in start  # denied before any job was spawned
    assert _children(start) == "denied"


@pytest.mark.parametrize("backend", BACKENDS)
def test_pcb003_non_member_default_fallback_is_204(backend, tmp_path):
    app, body = _app(backend, tmp_path)  # default fallback raises PreventUpdate
    start_status, _, _, _ = _run(backend, app, body, "guest")
    assert start_status == 204


@pytest.mark.parametrize("backend", BACKENDS)
def test_pcb004_anonymous_is_challenged(backend, tmp_path):
    app, body = _app(backend, tmp_path, missing_permissions_output="denied")
    start_status, _, _, _ = _run(backend, app, body, None)
    assert start_status == 401


def test_pcb005_background_callback_refused_over_websocket(tmp_path):
    """The job is registered ungated, so the WS path must not run it at all --
    not even for an authorised user (the renderer never sends it that way)."""
    pytest.importorskip("quart")
    app = Dash(__name__, backend="quart")
    auth = BasicAuth(app, USERS, user_groups={"admin": ["admin"]}, secret_key="T")
    out = f"out-{uuid.uuid4().hex}"
    app.layout = html.Div([html.Button(id="ws-btn"), html.Div(id=out)])

    @protected_callback(
        Output(out, "children"),
        Input("ws-btn", "n_clicks"),
        groups=["admin"],
        background=True,
        manager=DiskcacheManager(diskcache.Cache(str(tmp_path))),
    )
    def job(_n):
        return "ran"

    admin = {"email": "admin", "groups": ["admin"]}
    assert (
        auth.authorize_ws({"output": f"{out}.children", "inputs": []}, admin) is False
    )


@pytest.mark.parametrize("backend", BACKENDS)
def test_pcb006_denied_fallback_maps_wildcard_and_duplicate_outputs(backend, tmp_path):
    """The trigger: a wildcard (``ALL``) output's spec is a list, and an
    ``allow_duplicate`` output's property carries an ``@hash`` suffix. The old
    serialiser indexed the list spec as a dict (500) and leaked the suffix."""
    if backend != "flask":
        pytest.importorskip(backend)
    app = Dash(__name__, backend=backend)
    BasicAuth(app, USERS, user_groups={"admin": ["admin"]}, secret_key="Test!")
    kind, btn, out = (f"{p}-{uuid.uuid4().hex}" for p in ("item", "btn", "out"))
    app.layout = html.Div(
        [html.Button(id=btn), html.Div(id=out)]
        + [html.Div(id={"type": kind, "index": i}) for i in range(2)]
    )
    wild = Output({"type": kind, "index": ALL}, "children")
    dup = Output(out, "children", allow_duplicate=True)

    @protected_callback(
        [wild, dup],
        Input(btn, "n_clicks"),
        groups=["admin"],
        background=True,
        manager=DiskcacheManager(diskcache.Cache(str(tmp_path))),
        prevent_initial_call=True,
        missing_permissions_output=[["d0", "d1"], "denied"],
    )
    def job(_n):
        return [["r0", "r1"], "ran"]

    body = {
        "output": create_callback_id([wild, dup], [Input(btn, "n_clicks")], False),
        "outputs": [
            [
                {"id": {"type": kind, "index": i}, "property": "children"}
                for i in range(2)
            ],
            {"id": out, "property": dup.component_property},
        ],
        "inputs": [{"id": btn, "property": "n_clicks", "value": 1}],
        "changedPropIds": [f"{btn}.n_clicks"],
        "state": [],
    }
    start_status, start, _, _ = _run(backend, app, body, "guest")
    assert start_status == 200
    assert "cacheKey" not in start
    assert start["response"] == {
        stringify_id({"type": kind, "index": 0}): {"children": "d0"},
        stringify_id({"type": kind, "index": 1}): {"children": "d1"},
        out: {"children": "denied"},
    }

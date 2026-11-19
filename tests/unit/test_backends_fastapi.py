import pytest
from dash import Dash, html

pytest.importorskip("fastapi", reason="FastAPI extra dependencies are not installed")

from starlette.requests import Request

from dash_auth_async.backends import (
    FastAPIBackend,
    _current_request_var,
    detect_backend,
    get_active_backend,
    set_active_backend,
)

pytestmark = pytest.mark.usefixtures("reset_active_backend")


def _bare_request(path="/", session=None):
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
    }
    if session is not None:
        scope["session"] = session
    return Request(scope)


def test_detect_backend_fastapi():
    app = Dash(__name__, backend="fastapi")
    assert isinstance(detect_backend(app.server), FastAPIBackend)


def test_active_backend_roundtrip():
    backend = FastAPIBackend()
    set_active_backend(backend)
    assert get_active_backend() is backend


def test_contextvar_set_reset_and_request_context():
    backend = FastAPIBackend()
    assert backend.has_request_context() is False

    req = _bare_request()
    token = _current_request_var.set(req)
    try:
        assert backend.has_request_context() is True
        assert backend.request is req
    finally:
        _current_request_var.reset(token)
    assert backend.has_request_context() is False


def test_session_without_middleware_raises_runtimeerror():
    backend = FastAPIBackend()
    req = _bare_request()  # no "session" in scope
    token = _current_request_var.set(req)
    try:
        with pytest.raises(RuntimeError):
            _ = backend.session
    finally:
        _current_request_var.reset(token)


def test_session_off_request_raises_runtimeerror():
    # request is None outside any request context. The scope-based check
    # must surface RuntimeError (a caught, "not authenticated" signal), not
    # an AttributeError on None — and never relies on a -O-stripped assert.
    backend = FastAPIBackend()
    assert backend.request is None
    with pytest.raises(RuntimeError):
        _ = backend.session


def test_session_present_returns_mapping():
    backend = FastAPIBackend()
    req = _bare_request(session={"user": {"email": "a.b@mail.com"}})
    token = _current_request_var.set(req)
    try:
        assert backend.session["user"]["email"] == "a.b@mail.com"
    finally:
        _current_request_var.reset(token)


def test_coerce_response_tuple_str_and_response():
    from starlette.responses import Response as StarletteResponse

    backend = FastAPIBackend()

    # Tuples carry status/headers and stay plain text (e.g. the 401 challenge).
    resp = backend.coerce_response(
        ("Login Required", 401, {"WWW-Authenticate": 'Basic realm="x"'})
    )
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == 'Basic realm="x"'
    assert resp.body == b"Login Required"
    assert resp.media_type == "text/plain"

    # A bare string is treated as HTML, matching Flask/Quart str returns (e.g.
    # the OIDC logout page) so the browser renders rather than shows the markup.
    resp2 = backend.coerce_response("hello")
    assert resp2.status_code == 200
    assert resp2.body == b"hello"
    assert resp2.media_type == "text/html"

    passthrough = StarletteResponse(content="x", status_code=204)
    assert backend.coerce_response(passthrough) is passthrough


def test_fastapi_backend_url_for_and_redirect():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    backend = FastAPIBackend()

    @app.get("/target", name="target")
    async def target():
        return {"ok": True}

    @app.get("/probe")
    async def probe(request: Request):
        token = _current_request_var.set(request)
        try:
            return {
                "url": backend.url_for("target"),
                "https_url": backend.url_for("target", _external=True, _scheme="https"),
                "redirect_loc": backend.redirect("/target").headers["location"],
                "host": backend.current_host(),
            }
        finally:
            _current_request_var.reset(token)

    client = TestClient(app)
    data = client.get("/probe").json()
    assert data["url"].endswith("/target")
    assert data["https_url"].startswith("https://")
    assert data["redirect_loc"] == "/target"
    assert data["host"]  # non-empty netloc


def _build_app_with_auth(decide, needs_body):
    """A FastAPI app whose only middleware is the auth hook, plus an echo
    route that proves the body survives middleware body-consumption."""
    from fastapi import FastAPI

    app = FastAPI()
    backend = FastAPIBackend()

    @app.post("/_dash-update-component")
    async def echo(request: Request):
        body = await request.json()
        return {"seen": body, "had_context": backend.has_request_context()}

    @app.get("/open")
    async def open_route():
        return {"ok": True}

    backend.register_auth_hook(app, needs_body, decide)
    return app


def test_auth_hook_allows_when_decide_returns_none():
    from fastapi.testclient import TestClient

    calls = []

    def decide(path, body):
        calls.append((path, body))

    app = _build_app_with_auth(
        decide, needs_body=lambda p: p == "/_dash-update-component"
    )
    client = TestClient(app)

    r = client.post("/_dash-update-component", json={"output": "x", "inputs": []})
    assert r.status_code == 200
    # Body was replayed: the downstream route still parsed it.
    assert r.json()["seen"] == {"output": "x", "inputs": []}
    assert r.json()["had_context"] is True
    # decide saw the parsed body for the callback route.
    assert calls == [("/_dash-update-component", {"output": "x", "inputs": []})]


def test_auth_hook_short_circuits_with_tuple():
    from fastapi.testclient import TestClient

    def decide(path, body):
        return ("Login Required", 401, {"WWW-Authenticate": 'Basic realm="x"'})

    app = _build_app_with_auth(decide, needs_body=lambda p: False)
    client = TestClient(app)

    r = client.get("/open")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Basic realm="x"'
    assert r.text == "Login Required"


def test_auth_hook_awaits_coroutine_results():
    from fastapi.testclient import TestClient
    from starlette.responses import PlainTextResponse

    async def decide(path, body):
        return PlainTextResponse("async-block", status_code=403)

    app = _build_app_with_auth(decide, needs_body=lambda p: False)
    client = TestClient(app)

    r = client.get("/open")
    assert r.status_code == 403
    assert r.text == "async-block"


def test_auth_hook_unparseable_body_is_treated_as_none():
    # Fail-closed path: malformed JSON on a needs_body route must reach decide
    # as None (the `except Exception: body = None` branch), not raise a 500.
    from fastapi.testclient import TestClient

    seen = []

    def decide(path, body):
        seen.append(body)
        return ("Unauthorized", 401) if body is None else None

    app = _build_app_with_auth(
        decide, needs_body=lambda p: p == "/_dash-update-component"
    )
    client = TestClient(app)

    r = client.post(
        "/_dash-update-component",
        content="{ not valid json",
        headers={"content-type": "application/json"},
    )
    assert seen == [None]
    assert r.status_code == 401
    assert r.text == "Unauthorized"


def test_auth_hook_short_circuits_after_parsing_body():
    # The other short-circuit branch: decide returns non-None *when needs_body
    # is True*, so the body is parsed first and then the request is blocked.
    from fastapi.testclient import TestClient

    seen = []

    def decide(path, body):
        seen.append(body)
        return ("Login Required", 401)

    app = _build_app_with_auth(decide, needs_body=lambda p: True)
    client = TestClient(app)

    r = client.post("/_dash-update-component", json={"output": "x", "inputs": []})
    assert r.status_code == 401
    assert r.text == "Login Required"
    # decide saw the parsed body — it ran after body parsing, not before.
    assert seen == [{"output": "x", "inputs": []}]


def _drive_replay(client_messages):
    """Run the auth middleware over a fake request; collect the inner app's reads.

    ``client_messages`` is what the real ``receive`` yields in order; once it is
    exhausted the real receive blocks, as a live connection's does.

    Returns:
        The messages the inner app received: the replayed body, then whatever
        its second ``receive()`` returned within 0.2s (``"blocked"`` if none).
    """
    import asyncio

    from fastapi import FastAPI

    app = FastAPI()
    backend = FastAPIBackend()
    backend.register_auth_hook(
        app, needs_body=lambda p: True, decide=lambda path, body: None
    )
    # add_middleware prepends; our auth middleware is the only/outermost one.
    auth_middleware_cls = app.user_middleware[0].cls

    received = []

    async def inner_app(scope, receive, send):
        received.append(await receive())  # cached body
        try:
            received.append(await asyncio.wait_for(receive(), 0.2))
        except asyncio.TimeoutError:  # builtin TimeoutError only from 3.11
            received.append("blocked")

    middleware = auth_middleware_cls(inner_app)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/_dash-update-component",
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
    }
    pending = list(client_messages)

    async def receive():
        if pending:
            return pending.pop(0)
        await asyncio.Event().wait()  # connection still open: block forever
        return None

    async def send(_message):
        pass

    async def drive():
        await middleware(scope, receive, send)

    asyncio.run(drive())
    return received


BODY = {"type": "http.request", "body": b'{"output": "x"}', "more_body": False}


def test_downstream_receive_replays_body_then_forwards_real_disconnect():
    received = _drive_replay([BODY, {"type": "http.disconnect"}])

    assert received[0] == BODY
    assert received[1] == {"type": "http.disconnect"}


def test_downstream_receive_does_not_fake_disconnect_while_connected():
    """RED before fix: a fabricated http.disconnect after the body made
    StreamingResponse's disconnect listener cancel every streaming response
    (Dash 4.5 streaming callbacks and the stream downlink were cut short)."""
    received = _drive_replay([BODY])

    assert received == [BODY, "blocked"]


def test_setup_session_adds_session_middleware_once():
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware

    backend = FastAPIBackend()
    app = FastAPI()

    assert backend.session_configured(app) is False

    backend.setup_session(app, "Test!")
    assert backend.session_configured(app) is True
    count = sum(1 for m in app.user_middleware if m.cls is SessionMiddleware)
    assert count == 1

    # Calling again must not add a second SessionMiddleware.
    backend.setup_session(app, "Test!")
    count = sum(1 for m in app.user_middleware if m.cls is SessionMiddleware)
    assert count == 1


def test_setup_session_wires_secure_session_to_https_only():
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware

    backend = FastAPIBackend()

    insecure = FastAPI()
    backend.setup_session(insecure, "Test!")
    sm = next(m for m in insecure.user_middleware if m.cls is SessionMiddleware)
    assert sm.kwargs.get("https_only") is False

    secure = FastAPI()
    backend.setup_session(secure, "Test!", secure_session=True)
    sm = next(m for m in secure.user_middleware if m.cls is SessionMiddleware)
    assert sm.kwargs.get("https_only") is True


def test_setup_session_noop_without_secret_key():
    from fastapi import FastAPI

    backend = FastAPIBackend()
    app = FastAPI()
    backend.setup_session(app, None)
    assert backend.session_configured(app) is False


def test_config_store_read_roundtrip_via_state():
    from fastapi import FastAPI

    backend = FastAPIBackend()
    app = FastAPI()  # FastAPI has no .config, only .state

    assert backend.read_config(app, "PUBLIC_ROUTES", "fallback") == "fallback"
    backend.store_config(app, "PUBLIC_ROUTES", ["/home"])
    assert backend.read_config(app, "PUBLIC_ROUTES") == ["/home"]


def test_user_session_middleware_installed_before_auth_is_readable():
    """A ``SessionMiddleware`` the user installed *before* ``Auth(...)`` must
    still wrap the auth middleware.

    Regression: ``setup_session`` deferred to it but left it inside the auth
    middleware, so the session was unreadable there and every request raised
    ``RuntimeError`` -> 500.
    """
    from fastapi.testclient import TestClient
    from starlette.middleware.sessions import SessionMiddleware

    from dash_auth_async import OIDCAuth

    app = Dash(__name__, backend="fastapi")
    app.layout = html.Div("hi")
    app.server.add_middleware(SessionMiddleware, secret_key="Test!")
    oidc = OIDCAuth(app)  # no secret_key: defers to the user's middleware
    oidc.register_provider(
        "idp",
        client_id="x",
        client_secret="y",
        authorize_url="https://idp.example/auth",
        access_token_url="https://idp.example/token",
    )

    count = sum(1 for m in app.server.user_middleware if m.cls is SessionMiddleware)
    assert count == 1
    assert app.server.user_middleware[0].cls is SessionMiddleware  # outermost

    response = TestClient(app.server).get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example/auth")

"""Protected streams stop once the session that started them logs out.

A stream's caller is a snapshot captured at dispatch, which a cleared session
cookie can't reach: a page still open after logout (another tab, or a logout
done from elsewhere) kept receiving frames until the stream finished. Logout now
revokes the session id, and the protected stream wrapper checks it between
frames.
"""

import asyncio
import contextvars
import logging
import uuid

import dash
import pytest
from dash import Dash
from packaging.version import Version

from dash_auth_async import OIDCAuth, protected, stream_revocation as rev
from dash_auth_async.group_protection import _SID_NAMESPACE, _USER_NAMESPACE

pytestmark = [
    pytest.mark.skipif(
        Version(dash.__version__) < Version("4.5.0"),
        reason="streaming callbacks need dash>=4.5.0",
    ),
    pytest.mark.usefixtures("reset_active_backend", "isolated_callback_registry"),
]

ADMIN = {"email": "a@b.c", "groups": ["admin"]}


def _app(**kwargs):
    """Dash serves HTTP streams only with shared storage, so tests use one."""
    from dash import LocalSharedStorage  # dash>=4.5 only

    return Dash(
        __name__,
        shared_storage=LocalSharedStorage(namespace=uuid.uuid4().hex),
        **kwargs,
    )


def _run_stream(agen, sid, between=None, *, interval=0.0, monkeypatch):
    """Drain ``protected(...)(agen)`` as Dash would, with ``sid`` captured at
    dispatch; ``between`` runs after the first chunk.

    Returns:
        All chunks the wrapper yielded.
    """
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    monkeypatch.setattr(rev, "CHECK_INTERVAL", interval)
    stream = protected("login", groups=["admin"])(agen)

    async def drain():
        captured = {_USER_NAMESPACE: ADMIN, _SID_NAMESPACE: sid}
        context_value.set(AttributeDict(custom_data=AttributeDict(captured)))
        gen = stream(1)
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)
            if between is not None and len(chunks) == 1:
                between()
        return chunks

    # Fresh context: no Dash ctx or WS user left over from earlier tests.
    return contextvars.Context().run(asyncio.run, drain())


def test_slo001_logout_mid_stream_stops_it_with_the_fallback(monkeypatch):
    """RED before fix: every chunk reached the page after logout."""
    app = _app()
    cleaned_up = []

    async def agen(_n):
        try:
            for i in (1, 2, 3):
                yield f"chunk-{i}"
        finally:
            cleaned_up.append(True)

    chunks = _run_stream(
        agen,
        "sid-1",
        lambda: rev.revoke_session_streams(app, "sid-1"),
        monkeypatch=monkeypatch,
    )

    assert chunks == ["chunk-1", "login"]
    assert cleaned_up == [True]


def test_slo002_stream_started_by_a_revoked_session_never_runs(monkeypatch):
    """A replayed pre-logout cookie must not start a protected stream."""
    app = _app()
    started = []

    async def agen(_n):
        started.append(True)
        yield "chunk-1"

    rev.revoke_session_streams(app, "sid-old")
    chunks = _run_stream(agen, "sid-old", monkeypatch=monkeypatch)

    assert chunks == ["login"]
    assert started == []


def test_slo003_store_failure_fails_closed_and_logs(monkeypatch, caplog):
    _app()

    async def agen(_n):
        yield "chunk-1"

    def broken(*_args):
        raise ConnectionError("store down")

    monkeypatch.setattr(rev, "_read_revoked", broken)
    with caplog.at_level(logging.WARNING, logger=rev.__name__):
        chunks = _run_stream(agen, "sid-1", monkeypatch=monkeypatch)

    assert chunks == ["login"]
    assert "store down" in caplog.text


def test_slo004_lookups_are_throttled_per_stream(monkeypatch):
    """A fast stream must not hit the store on every frame."""
    _app()
    lookups = []
    monkeypatch.setattr(rev, "_read_revoked", lambda *_a: lookups.append(1) or False)

    async def agen(_n):
        for i in range(50):
            yield i

    chunks = _run_stream(agen, "sid-1", interval=60.0, monkeypatch=monkeypatch)

    assert chunks == list(range(50))
    assert len(lookups) == 1  # the start check only


def test_slo005_stream_without_a_session_id_is_not_checked(monkeypatch):
    """BasicAuth (no logout) and non-OIDC sessions carry no sid: nothing to revoke."""
    _app()
    lookups = []
    monkeypatch.setattr(rev, "_read_revoked", lambda *_a: lookups.append(1) or False)

    async def agen(_n):
        yield "chunk-1"
        yield "chunk-2"

    assert _run_stream(agen, None, monkeypatch=monkeypatch) == ["chunk-1", "chunk-2"]
    assert lookups == []


def test_slo006_revocation_goes_to_shared_storage_with_a_ttl(monkeypatch):
    """With shared storage every worker sees the revocation; it must expire."""
    app = _app()
    writes = []
    real_set = app.shared_storage.set
    monkeypatch.setattr(
        app.shared_storage,
        "set",
        lambda key, value, ttl=None: writes.append(ttl) or real_set(key, value, ttl),
    )

    rev.revoke_session_streams(app, "sid-1")

    assert writes == [rev.REVOKED_TTL]
    assert rev.is_session_revoked(app, "sid-1")
    assert not rev.is_session_revoked(app, "sid-2")


def test_slo012_without_shared_storage_revocation_is_a_quiet_no_op(caplog):
    """No shared storage: no HTTP streams to stop, and logout (on any Dash
    version) must not log errors for it."""
    app = Dash(__name__)
    with caplog.at_level(logging.ERROR, logger=rev.__name__):
        rev.revoke_session_streams(app, "sid-1")
    assert not rev.is_session_revoked(app, "sid-1")
    assert not caplog.text


def _oidc_app():
    app = _app()
    app.layout = dash.html.Div("page")
    auth = OIDCAuth(app, secret_key="Test")
    auth.register_provider(
        "oidc",
        token_endpoint_auth_method="client_secret_post",
        client_id="<client-id>",
        client_secret="<client-secret>",
        server_metadata_url="https://idp.example/.well-known/openid-configuration",
    )
    return app, auth


def test_slo007_login_mints_a_fresh_session_id():
    app, auth = _oidc_app()
    with app.server.test_request_context("/"):
        auth.after_logged_in(dict(ADMIN), "oidc", {})
        first = auth.session[rev.SESSION_ID_KEY]
        auth.session.clear()
        auth.after_logged_in(dict(ADMIN), "oidc", {})
        assert auth.session[rev.SESSION_ID_KEY] != first


def test_slo008_session_from_before_the_upgrade_gets_an_id_lazily():
    app, _auth = _oidc_app()
    client = app.server.test_client()
    with client.session_transaction() as session:
        session["user"] = dict(ADMIN)

    assert client.get("/").status_code == 200
    with client.session_transaction() as session:
        assert session.get(rev.SESSION_ID_KEY)


def test_slo009_logout_revokes_the_session_id():
    app, _auth = _oidc_app()
    client = app.server.test_client()
    with client.session_transaction() as session:
        session["user"] = dict(ADMIN)
        session[rev.SESSION_ID_KEY] = "sid-1"

    assert client.get("/oidc/logout").status_code == 200

    assert rev.is_session_revoked(app, "sid-1")
    with client.session_transaction() as session:
        assert rev.SESSION_ID_KEY not in session


def test_slo010_failed_revocation_still_logs_out(monkeypatch, caplog):
    """A store outage must not leave the user logged in."""
    app, _auth = _oidc_app()
    client = app.server.test_client()
    with client.session_transaction() as session:
        session["user"] = dict(ADMIN)
        session[rev.SESSION_ID_KEY] = "sid-1"

    def broken(*_args):
        raise ConnectionError("store down")

    monkeypatch.setattr(rev, "_write_revoked", broken)
    with caplog.at_level(logging.ERROR, logger=rev.__name__):
        assert client.get("/oidc/logout").status_code == 200

    assert "store down" in caplog.text
    with client.session_transaction() as session:
        assert "user" not in session


def test_slo014_default_fallback_ends_a_revoked_stream_with_prevent_update(
    monkeypatch,
):
    """protected_callback's default fallback raises PreventUpdate, which Dash
    treats as a clean end of stream; the user generator must still close."""
    from dash import Input, Output
    from dash._callback_context import context_value
    from dash._utils import AttributeDict
    from dash.exceptions import PreventUpdate

    from dash_auth_async import protected_callback

    app = _app()
    cleaned_up = []

    async def agen(_n):
        try:
            yield "chunk-1"
            yield "chunk-2"
        finally:
            cleaned_up.append(True)

    tag = uuid.uuid4().hex
    stream = protected_callback(
        Output(f"out-{tag}", "children"),
        Input(f"btn-{tag}", "n_clicks"),
        prevent_initial_call=True,
    )(agen)

    async def drain():
        captured = {_USER_NAMESPACE: ADMIN, _SID_NAMESPACE: "sid-1"}
        context_value.set(AttributeDict(custom_data=AttributeDict(captured)))
        gen = stream(1)
        assert await anext(gen) == "chunk-1"
        rev.revoke_session_streams(app, "sid-1")
        with pytest.raises(PreventUpdate):
            await anext(gen)

    monkeypatch.setattr(rev, "CHECK_INTERVAL", 0.0)
    contextvars.Context().run(asyncio.run, drain())
    assert cleaned_up == [True]

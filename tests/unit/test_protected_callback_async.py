"""Unit tests regarding protected sync and async callbacks."""

import asyncio
import inspect

import pytest
from dash import Input, Output
from dash._callback import GLOBAL_CALLBACK_MAP
from dash.exceptions import PreventUpdate
from flask import Flask, session

from dash_auth_async import protected, protected_callback, public_callback

AUTHORIZED_SESSION = {"email": "a.b@mail.com", "groups": ["default"]}


# --------------------------------------------------------------------------- #
# Level 1: protected() preserves the coroutine contract
# --------------------------------------------------------------------------- #
def test_gp005_protected_keeps_sync_target_sync():
    """CONTROL: wrapping a sync target yields a plain (non-coroutine) callable."""

    def func():
        return "success"

    wrapped = protected(unauthenticated_output="unauth", groups=["default"])(func)

    assert not inspect.iscoroutinefunction(wrapped)


def test_gp006_protected_keeps_async_target_async():
    """RED: wrapping an async target must yield a coroutine function.

    Fails today: ``protected`` returns a synchronous ``def wrap`` regardless of
    the target, so Dash registers it on the sync dispatch path.
    """

    async def func():
        return "success"

    wrapped = protected(unauthenticated_output="unauth", groups=["default"])(func)

    assert inspect.iscoroutinefunction(wrapped)


# --------------------------------------------------------------------------- #
# Level 2: behaviour (auth gating) is preserved once async is honoured
# --------------------------------------------------------------------------- #
def test_gp007_async_protected_returns_inner_value_when_authorized():
    """RED-spec: an authorized async target's value survives the wrapper."""

    async def func():
        return "success"

    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = dict(AUTHORIZED_SESSION)
        wrapped = protected(unauthenticated_output="unauth", groups=["default"])(func)

        assert inspect.iscoroutinefunction(wrapped)
        assert asyncio.run(wrapped()) == "success"


def test_gp008_async_protected_emits_missing_permissions_output():
    """RED-spec: an authenticated user lacking the group gets the forbidden output."""

    async def func():
        return "success"

    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = dict(AUTHORIZED_SESSION)
        wrapped = protected(
            unauthenticated_output="unauth",
            missing_permissions_output="forbidden",
            groups=["admin"],
        )(func)

        assert inspect.iscoroutinefunction(wrapped)
        assert asyncio.run(wrapped()) == "forbidden"


def test_gp008b_async_protected_emits_unauthenticated_output_without_session_user():
    """An async target with no session user gets the unauthenticated output.

    The third gate branch (alongside authorized and missing-permissions): when
    ``_current_user`` resolves to ``None`` the wrapper must short-circuit to
    ``unauthenticated_output`` and never await the inner coroutine -- while still
    staying a coroutine function so Dash keeps it on the async dispatch path.
    """

    async def func():
        return "success"

    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        # No session["user"] -> unauthenticated.
        wrapped = protected(
            unauthenticated_output="unauthenticated",
            missing_permissions_output="forbidden",
            groups=["admin"],
        )(func)

        assert inspect.iscoroutinefunction(wrapped)
        assert asyncio.run(wrapped()) == "unauthenticated"


# --------------------------------------------------------------------------- #
# Level 3: protected_callback registers on the correct Dash dispatch path
# --------------------------------------------------------------------------- #
def _register_and_get_dispatch(decorate, target):
    """Apply ``decorate`` to ``target`` and return the callable Dash stored.

    Snapshots ``GLOBAL_CALLBACK_MAP`` so we read back exactly the entry this
    registration added (the map is process-global and other tests populate it).
    The stored callable is ``async_add_context`` or ``add_context`` -- whichever
    Dash chose from the target's coroutine flag.
    """
    before = set(GLOBAL_CALLBACK_MAP)
    decorate(target)
    new_ids = set(GLOBAL_CALLBACK_MAP) - before
    assert len(new_ids) == 1, f"expected exactly one new callback, got {len(new_ids)}"
    return GLOBAL_CALLBACK_MAP[new_ids.pop()]["callback"]


def test_gp009_protected_callback_registers_sync_dispatch_for_sync_target():
    """CONTROL: a sync target lands on Dash's synchronous dispatch path."""

    def decorate(func):
        return protected_callback(
            Output("gp009-out", "children"),
            Input("gp009-in", "n_clicks"),
            prevent_initial_call=True,
        )(func)

    def target(_n_clicks):
        return "ok"

    dispatch = _register_and_get_dispatch(decorate, target)

    assert not inspect.iscoroutinefunction(dispatch)


def test_gp010_protected_callback_registers_async_dispatch_for_async_target():
    """RED: an async target must land on Dash's async dispatch path.

    Fails today: ``protected_callback`` hands Dash a sync wrapper, so Dash stores
    ``add_context`` and the coroutine is never awaited over the WebSocket.
    """

    def decorate(func):
        return protected_callback(
            Output("gp010-out", "children"),
            Input("gp010-in", "n_clicks"),
            prevent_initial_call=True,
        )(func)

    async def target(_n_clicks):
        return "ok"

    dispatch = _register_and_get_dispatch(decorate, target)

    assert inspect.iscoroutinefunction(dispatch)


# --------------------------------------------------------------------------- #
# Level 4: streaming (generator) targets keep their function kind
# --------------------------------------------------------------------------- #
# Dash 4.5 branches on isgeneratorfunction / isasyncgenfunction at registration
# to pick its streaming path. A plain ``def wrap`` erased both: the generator was
# returned unconsumed as the callback's value.
async def _agen_target():
    yield "chunk-1"
    yield "chunk-2"


def _gen_target():
    yield "chunk-1"
    yield "chunk-2"


async def _drain(agen):
    return [chunk async for chunk in agen]


def _gate(groups):
    return protected(
        unauthenticated_output="unauthenticated",
        missing_permissions_output="forbidden",
        groups=groups,
    )


def test_gp011_protected_keeps_async_generator_target_async_generator():
    """RED before fix: an async-generator target must stay an async generator."""
    assert inspect.isasyncgenfunction(_gate(["default"])(_agen_target))


def test_gp012_protected_keeps_generator_target_generator():
    """RED before fix: a sync-generator target must stay a generator."""
    assert inspect.isgeneratorfunction(_gate(["default"])(_gen_target))


def test_gp013_async_generator_streams_all_chunks_when_authorized():
    """An authorized user receives every chunk, in order."""
    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        session["user"] = dict(AUTHORIZED_SESSION)
        wrapped = _gate(["default"])(_agen_target)
        assert asyncio.run(_drain(wrapped())) == ["chunk-1", "chunk-2"]


def test_gp014_async_generator_yields_only_fallback_when_denied():
    """Denied users get exactly one fallback chunk; the target never runs."""
    started = []

    async def target():
        started.append(True)
        yield "secret"

    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        assert asyncio.run(_drain(_gate(["admin"])(target)())) == ["unauthenticated"]
        session["user"] = dict(AUTHORIZED_SESSION)
        assert asyncio.run(_drain(_gate(["admin"])(target)())) == ["forbidden"]
    assert started == []


def test_gp015_generator_streams_when_authorized_and_falls_back_when_denied():
    """Sync-generator twin of gp013/gp014."""
    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"):
        assert list(_gate(["default"])(_gen_target)()) == ["unauthenticated"]
        session["user"] = dict(AUTHORIZED_SESSION)
        assert list(_gate(["default"])(_gen_target)()) == ["chunk-1", "chunk-2"]
        assert list(_gate(["admin"])(_gen_target)()) == ["forbidden"]


def test_gp016_raising_fallback_propagates_from_async_generator():
    """The default fallback raises PreventUpdate; it must surface from the stream."""

    def deny():
        raise PreventUpdate

    wrapped = protected(
        unauthenticated_output=deny,
        groups=["admin"],
    )(_agen_target)

    app = Flask(__name__)
    app.secret_key = "Test!"
    with app.test_request_context("/", method="GET"), pytest.raises(PreventUpdate):
        asyncio.run(_drain(wrapped()))


# --------------------------------------------------------------------------- #
# Level 5: the name returned by the callback decorators keeps its kind
# --------------------------------------------------------------------------- #
async def _kind_coro(_n):
    return "ok"


async def _kind_agen(_n):
    yield "ok"


def _kind_sync(_n):
    return "ok"


_KIND_CHECKS = (
    inspect.iscoroutinefunction,
    inspect.isasyncgenfunction,
    inspect.isgeneratorfunction,
)


# Sync generators are absent: Dash 4.5 rejects them at registration
# (StreamCallbackError); protected() keeps their kind so that error surfaces.
@pytest.mark.usefixtures("isolated_callback_registry")
@pytest.mark.parametrize("decorator", [public_callback, protected_callback])
@pytest.mark.parametrize("target", [_kind_coro, _kind_agen, _kind_sync])
def test_gp017_callback_decorators_return_target_kind(decorator, target):
    """RED before fix: both decorators returned a plain ``def wrap`` forwarder.

    Dash itself registered the right function, but the name bound in the user's
    module became a sync function -- breaking stacked decorators and any
    caller that inspects or awaits/iterates it.
    """
    out_id = f"gp017-{decorator.__name__}-{target.__name__}"
    decorated = decorator(
        Output(out_id, "children"),
        Input(f"{out_id}-in", "n_clicks"),
        prevent_initial_call=True,
    )(target)

    for kind_check in _KIND_CHECKS:
        assert kind_check(decorated) == kind_check(target)


def test_gp018_capture_user_fails_closed_and_logs(monkeypatch, caplog):
    """A broken user lookup must deny (None), but visibly: a silent None would
    look like "every user is denied" with nothing in the logs."""
    from dash_auth_async import group_protection

    def boom():
        raise RuntimeError("no session")

    monkeypatch.setattr(group_protection, "_current_user", boom)
    with caplog.at_level("DEBUG", logger=group_protection.__name__):
        assert group_protection._capture_user(None) is None
    assert "Could not resolve the caller" in caplog.text


def test_gp019_user_capture_hook_skipped_without_dash_hooks(monkeypatch):
    """Dash below 3 has no hooks (and no streams): installing must not crash."""
    import dash

    from dash_auth_async import group_protection

    monkeypatch.delattr(dash, "hooks", raising=False)
    monkeypatch.setattr(group_protection, "_user_capture_installed", False)
    group_protection._install_user_capture_hook()
    assert group_protection._user_capture_installed is False

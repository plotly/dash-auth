"""Group-based protection for Dash callbacks and outputs."""

import contextlib
import functools
import inspect
import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any, Literal

import dash
from dash import get_app

# The helpers Dash uses internally to key its callback map and serialise
# responses; no public API equivalent.
from dash._grouping import flatten_grouping  # noqa: PLC2701
from dash._no_update import NoUpdate  # noqa: PLC2701 — Dash's no_update check
from dash._utils import (  # noqa: PLC2701
    clean_property_name,
    create_callback_id,
    stringify_id,
    to_json,
)
from dash.dependencies import Output, handle_grouped_callback_args
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from . import stream_revocation
from .backends import detect_backend, get_active_backend
from .stream_revocation import SESSION_ID_KEY
from .websocket_auth import _WS_AUTH_USER

OutputVal = Callable[[], Any] | Any
CheckType = Literal["one_of", "all_of", "none_of"]

# Sentinel: the gate authorises the call, so run the protected target rather
# than substitute a fallback output (a fallback may legitimately be None/falsy).
_PROCEED = object()


def _current_user() -> dict | None:
    """Resolve the authenticated user for the current dispatch.

    Single source of truth for "who is calling": under an HTTP request context
    this is the framework session user; on the WebSocket worker path (no
    framework context) it is the user the websocket_message hook stashed in
    ``_WS_AUTH_USER`` for this dispatch. Returns ``None`` when unauthenticated.

    Every helper that needs the caller -- ``list_groups`` and the default
    ``protected_callback`` fallbacks -- goes through here so none of them touch
    ``backend.session`` directly (which raises ``RuntimeError`` off-request).

    Returns:
        The authenticated user dict, or None when unauthenticated.
    """
    backend = get_active_backend()
    if backend.has_request_context():
        # Normal HTTP path: read the user from the framework session.
        try:
            return backend.session.get("user")
        except RuntimeError:
            # Session unavailable (e.g. FastAPI without SessionMiddleware):
            # treat as not authenticated rather than crashing.
            return None
    # WebSocket worker path: no framework context here, so read the user the
    # websocket_message hook stashed for this dispatch.
    return _WS_AUTH_USER.get()


def list_groups(
    *,
    groups_key: str = "groups",
    groups_str_split: str | None = None,
) -> list[str] | None:
    """List all the groups the user belongs to.

    :param groups_key: Groups key in the user data saved in the backend session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string

    Returns:
        None if the user is not authenticated, otherwise the list of groups.
    """
    user = _current_user()
    if user is None:
        return None

    user_groups = user.get(groups_key, [])
    # Handle cases where groups are ,- or ;-separated string,
    # may depend on OIDC provider
    if isinstance(user_groups, str) and groups_str_split is not None:
        user_groups = re.split(groups_str_split, user_groups)
    return user_groups


def check_groups(
    groups: list[str] | None = None,
    *,
    groups_key: str = "groups",
    groups_str_split: str | None = None,
    check_type: CheckType = "one_of",
) -> bool | None:
    """Check whether the current user is authenticated and has the groups.

    :param groups: List of groups to check for with check_type
    :param groups_key: Groups key in the user data saved in the backend session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string
    :param check_type: Type of check to perform.
        Either "one_of", "all_of" or "none_of"

    Returns:
        None if the user is not authenticated; True if authenticated with the
        right permissions; False if authenticated without them.

    Raises:
        ValueError: if ``check_type`` is not a recognised value.
    """
    user_groups = list_groups(
        groups_key=groups_key,
        groups_str_split=groups_str_split,
    )

    if user_groups is None:
        # User is not authenticated
        return None

    if groups is None:
        return True

    if check_type == "one_of":
        return bool(set(user_groups).intersection(groups))
    if check_type == "all_of":
        return all(group in user_groups for group in groups)
    if check_type == "none_of":
        return not any(group in user_groups for group in groups)

    raise ValueError(f"Invalid check_type: {check_type}")


def protected(  # noqa: PLR0913 — public decorator with many optional knobs
    unauthenticated_output: OutputVal,
    *,
    missing_permissions_output: OutputVal | None = None,
    groups: list[str] | None = None,
    groups_key: str = "groups",
    groups_str_split: str | None = None,
    check_type: CheckType = "one_of",
) -> Callable:
    """Alter a function or output depending on authentication and permissions.

    :param unauthenticated_output: Output when the user is not authenticated.
        Note: needs to be a function with no argument or static outputs.
    :param missing_permissions_output: Output when the user is authenticated
        but does not have the right permissions.
        It defaults to unauthenticated_output when not set.
        Note: needs to be a function with no argument or static outputs.
    :param groups: List of authorized user groups. If no groups are passed,
        the decorator will only check whether the user is authenticated.
    :param groups_key: Groups key in the user data saved in the Flask session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string
    :param check_type: Type of check to perform.
        Either "one_of", "all_of" or "none_of"

    Returns:
        A decorator that wraps the target output with the auth gate.
    """
    if missing_permissions_output is None:
        missing_permissions_output = unauthenticated_output

    def decorator(output: OutputVal):
        def evaluate(value: OutputVal) -> Any:
            # Fallback outputs are documented as no-argument callables or
            # static values.
            return value() if isinstance(value, Callable) else value

        def gate() -> Any:
            """Return _PROCEED when authorised, else the fallback output."""
            authorized = check_groups(
                groups=groups,
                groups_key=groups_key,
                groups_str_split=groups_str_split,
                check_type=check_type,
            )
            if authorized is None:
                return evaluate(unauthenticated_output)
            if not authorized:
                return evaluate(missing_permissions_output)
            return _PROCEED

        # Every wrapper must keep the target's function kind: Dash picks the
        # dispatch path at registration from iscoroutinefunction /
        # isgeneratorfunction / isasyncgenfunction (dash _callback.py). A plain
        # def wrapper erases it -- a coroutine is never awaited, a streaming
        # generator is returned unconsumed.
        if isinstance(output, Callable) and inspect.isasyncgenfunction(output):
            # A stream's body runs where no session is readable (Flask drives it
            # on a private loop thread), so gate it with the user captured at
            # dispatch. A denied user's fallback then travels as a normal
            # stream frame -- the only thing a multiplexed renderer reads.
            _install_user_capture_hook()

            @functools.wraps(output)
            async def agen_wrap(*args, **kwargs):
                sid = _adopt_dispatch_user()
                logged_out = _logout_watch(sid)
                if next(logged_out):
                    yield evaluate(unauthenticated_output)
                    return
                fallback = gate()
                if fallback is not _PROCEED:
                    yield fallback
                    return
                # aclosing: when Dash closes this stream (cancel/disconnect),
                # close the user's generator now so its cleanup runs promptly.
                async with contextlib.aclosing(output(*args, **kwargs)) as chunks:
                    async for chunk in chunks:
                        # Not gate(): it may still see the stale request
                        # session; the logout is only visible in the store.
                        if next(logged_out):
                            yield evaluate(unauthenticated_output)
                            return
                        yield chunk

            return agen_wrap

        if isinstance(output, Callable) and inspect.isgeneratorfunction(output):

            @functools.wraps(output)
            def gwrap(*args, **kwargs):
                fallback = gate()
                if fallback is not _PROCEED:
                    yield fallback
                    return
                yield from output(*args, **kwargs)

            return gwrap

        if isinstance(output, Callable) and inspect.iscoroutinefunction(output):

            @functools.wraps(output)
            async def awrap(*args, **kwargs):
                fallback = gate()
                if fallback is _PROCEED:
                    return await output(*args, **kwargs)
                return fallback

            return awrap

        def wrap(*args, **kwargs):
            fallback = gate()
            if fallback is not _PROCEED:
                return fallback
            if isinstance(output, Callable):
                return output(*args, **kwargs)
            return output

        if isinstance(output, Callable):
            return wrap
        return wrap()

    return decorator


def _prevent_unauthenticated(func_name: str) -> None:
    """Default ``unauthenticated_output``: log and stop the callback.

    Raises:
        PreventUpdate: always, to stop the callback from running.
    """
    logging.info(
        "A user tried to run %s without being authenticated.",
        func_name,
    )
    raise PreventUpdate


def _prevent_unauthorised(func_name: str) -> None:
    """Default ``missing_permissions_output``: log and stop the callback.

    Resolves the caller via ``_current_user`` rather than touching
    ``backend.session`` directly, so it stays graceful on the WebSocket worker
    path (no request context) instead of raising ``RuntimeError``.

    Raises:
        PreventUpdate: always, to stop the callback from running.
    """
    user = _current_user() or {}
    logging.info(
        "%s tried to run %s but did not have the right permissions.",
        user.get("email", "<unknown user>"),
        func_name,
    )
    raise PreventUpdate


def protected_callback(  # noqa: PLR0913 — public decorator with many optional knobs
    *callback_args,
    unauthenticated_output: OutputVal | None = None,
    missing_permissions_output: OutputVal | None = None,
    groups: list[str] | None = None,
    groups_key: str = "groups",
    groups_str_split: str | None = None,
    check_type: CheckType = "one_of",
    **callback_kwargs,
) -> Callable:
    """Protected Dash callback.

    :param **: all args and kwargs passed to a Dash callback
    :param unauthenticated_output: Output when the user is not authenticated.
        **Note**: Needs to be a function with no argument or static outputs.
        You can access the Dash callback context within the function call if
        you need to use some of the inputs/states of the callback.
        If left as None, it will simply raise PreventUpdate, stopping the
        callback from processing.
    :param missing_permissions_output: Output when the user is authenticated
        but does not have the right permissions.
        It defaults to unauthenticated_output when not set.
        **Note**: Needs to be a function with no argument or static outputs.
        You can access the Dash callback context within the function call if
        you need to use some of the inputs/states of the callback.
        If left as None, it will simply raise PreventUpdate, stopping the
        callback from processing.
    :param groups: List of authorized user groups
    :param groups_key: Groups key in the user data saved in the backend session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string
    :param check_type: Type of check to perform.
        Either "one_of", "all_of" or "none_of"

    Returns:
        A decorator that registers the protected Dash callback.
    """

    def decorator(func):
        guard = protected(
            unauthenticated_output=(
                unauthenticated_output
                if unauthenticated_output is not None
                else functools.partial(_prevent_unauthenticated, func.__name__)
            ),
            missing_permissions_output=(
                missing_permissions_output
                if missing_permissions_output is not None
                else functools.partial(_prevent_unauthorised, func.__name__)
            ),
            groups=groups,
            groups_key=groups_key,
            groups_str_split=groups_str_split,
            check_type=check_type,
        )
        if callback_kwargs.get("background"):
            # A background job runs in another process with no session, so the
            # gate can't run inside it (it would always deny). Gate at HTTP
            # dispatch instead -- Auth._authorize, on the start request and
            # every poll -- and register the job unwrapped. Registered first so
            # a failure leaves no ungated callback behind.
            _register_dispatch_gate(callback_args, callback_kwargs, guard(_proceed))
            target = func
        else:
            target = guard(func)
        wrapped_func = dash.callback(*callback_args, **callback_kwargs)(target)

        # Return Dash's result as-is: a plain forwarding def would erase the
        # coroutine/generator kind of the user's function.
        return wrapped_func

    return decorator


DISPATCH_GATES = "PROTECTED_DISPATCH_GATED_CALLBACKS"


def _proceed() -> object:
    """Target for the dispatch-time gate: reached only when authorised.

    Returns:
        The ``_PROCEED`` sentinel.
    """
    return _PROCEED


_USER_NAMESPACE = "dash_auth_async_user"
_SID_NAMESPACE = "dash_auth_async_sid"
_user_capture_lock = threading.Lock()
_user_capture_installed = False
logger = logging.getLogger(__name__)


def _capture_user(_ctx) -> dict | None:
    """``custom_data`` hook: the caller, resolved while dispatch has context.

    Returns:
        The authenticated user, or None. Errors deny (fail closed) but are
        logged, so a broken hook does not just look like "everyone is denied".
        Apps without an ``Auth`` land here too: the hook is process-global.
    """
    try:
        return _current_user()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Could not resolve the caller for a callback.", exc_info=True)
        return None


def _capture_session_id(_ctx) -> str | None:
    """``custom_data`` hook: the caller's revocable session id, if any.

    Only readable under an HTTP request; over a WebSocket the logout closes the
    socket itself (``close_authenticated_ws``), which ends its streams.

    Returns:
        The session id, or None (no request, no session, or no id).
    """
    backend = get_active_backend()
    if not backend.has_request_context():
        return None
    try:
        return backend.session.get(SESSION_ID_KEY)
    except RuntimeError:  # no session configured on this server
        return None


def _install_user_capture_hook() -> None:
    """Register the dispatch-capture hooks once per process (they are global)."""
    global _user_capture_installed  # noqa: PLW0603 — once-per-process guard
    hooks = getattr(dash, "hooks", None)
    if hooks is None:  # dash<3: no hooks, and no streaming callbacks either
        return
    with _user_capture_lock:
        if not _user_capture_installed:
            hooks.custom_data(_USER_NAMESPACE)(_capture_user)
            hooks.custom_data(_SID_NAMESPACE)(_capture_session_id)
            _user_capture_installed = True


def _adopt_dispatch_user() -> str | None:
    """Make the user captured at dispatch the caller for this stream.

    Dash runs ``custom_data`` hooks while it still has the request (or WS)
    context and restores ``dash.ctx`` around every stream step. Setting the
    captured user as the off-request user lets ``_current_user()`` see it
    wherever the stream is consumed. Outside a Dash dispatch (no ctx, or the
    hook did not run) this changes nothing.

    Returns:
        The session id captured at dispatch, or None.
    """
    try:
        custom_data = dash.callback_context.custom_data
    # No ctx yet (LookupError), ctx outside a callback, or dash<3 (AttributeError).
    except (LookupError, MissingCallbackContextException, AttributeError):
        return None
    if _USER_NAMESPACE in custom_data:
        # No reset needed: the value lives in the context of the task (or
        # copied step context) driving this one stream, which ends with it.
        _WS_AUTH_USER.set(custom_data[_USER_NAMESPACE])
    return custom_data.get(_SID_NAMESPACE)


def _logout_watch(sid: str | None):
    """Yield, once per stream frame, whether ``sid`` has logged out.

    Checks the store at most every ``CHECK_INTERVAL`` seconds and answers
    False in between. Once revoked, stays revoked.

    Yields:
        True when the stream must stop.
    """
    if not sid:  # no revocable session (e.g. BasicAuth): nothing to watch
        while True:
            yield False
    app = get_app()
    next_check = 0.0
    while True:
        now = time.monotonic()
        if now >= next_check:
            if stream_revocation.is_session_revoked(app, sid):
                while True:
                    yield True
            next_check = now + stream_revocation.CHECK_INTERVAL
        yield False


def _register_dispatch_gate(callback_args, callback_kwargs, gate: Callable) -> None:
    """Record ``gate`` to run at HTTP dispatch, keyed like ``public_callback``.

    Raises:
        RuntimeError: when no Dash app exists yet. Fails loudly because the
            callback itself is registered ungated -- silently skipping the gate (as
            ``public_callback`` may skip its whitelist) would leave it open.
    """
    output, inputs, _state, _indices, _prevent = handle_grouped_callback_args(
        callback_args, callback_kwargs
    )
    # Same id Dash computes in register_callback, so dispatch lookups match.
    flat_output = output if isinstance(output, Output) else flatten_grouping(output)
    callback_id = create_callback_id(flat_output, inputs, no_output=not flat_output)
    try:
        app = get_app()
    except Exception as err:
        raise RuntimeError(
            "protected_callback(background=True) must be registered after the "
            "Dash app is created: the group check runs at request dispatch."
        ) from err
    backend = detect_backend(app.server)
    gates = backend.read_config(app.server, DISPATCH_GATES, {})
    backend.store_config(
        app.server, DISPATCH_GATES, {**gates, callback_id: (gate, output)}
    )


def refuses_ws(app, output: str | None) -> bool:
    """Whether ``output`` is dispatch-gated and must not run over a WebSocket.

    Returns:
        True for group-protected background callbacks, whose gate runs only in
        ``Auth._authorize`` (over HTTP).
    """
    backend = detect_backend(app.server)
    return output in backend.read_config(app.server, DISPATCH_GATES, {})


def dispatch_gate_response(app, body: dict | None) -> Any:
    """Run a dispatch-gated callback's group gate for an authorised request.

    Called from ``Auth._authorize`` under the request context, where
    ``_current_user()`` can read the session -- unlike a background job process.

    Returns:
        None to let the request proceed (start or poll the job), ``("", 204)``
        when the fallback raised ``PreventUpdate`` or updates nothing, or a Dash
        callback response carrying the fallback output -- so a denied user
        never spawns a job.
    """
    if not body:  # _authorize already rejects bodiless callback requests
        return None
    backend = detect_backend(app.server)
    entry = backend.read_config(app.server, DISPATCH_GATES, {}).get(body.get("output"))
    if entry is None:
        return None
    gate, output = entry
    try:
        fallback = gate()
    except PreventUpdate:
        return "", 204
    if fallback is _PROCEED:
        return None
    response = _callback_response(output, body.get("outputs"), fallback)
    if not response:  # Dash answers an all-no_update result with 204 too
        return "", 204
    return (
        to_json({"multi": True, "response": response}),
        200,
        {"Content-Type": "application/json"},
    )


def _callback_response(output: Any, outputs: Any, value: Any) -> dict:
    """Map ``value`` onto the request's output specs, as Dash's own dispatch does.

    Mirrors ``dash._callback._prepare_response``: a wildcard (``ALL``/
    ``ALLSMALLER``) output's spec is a list, matched item-by-item against a list
    value; ``prop@hash`` (``allow_duplicate``) is reduced to ``prop``.

    Returns:
        ``{component_id: {prop: value}}``; empty when nothing is updated.
    """
    if isinstance(output, Output):
        value, outputs = [value], [outputs]
    elif NoUpdate.is_no_update(value):
        return {}
    else:
        value = flatten_grouping(
            list(value) if isinstance(value, tuple) else value, output
        )
    response: dict = {}
    for val, spec in zip(value, outputs, strict=True):
        if NoUpdate.is_no_update(val):
            continue
        # A wildcard output's spec is a list, matched item-by-item to a list value.
        vals, specs = (val, spec) if isinstance(spec, list) else ([val], [spec])
        for vali, speci in zip(vals, specs, strict=True):
            if not NoUpdate.is_no_update(vali):
                prop = clean_property_name(speci["property"])
                response.setdefault(stringify_id(speci["id"]), {})[prop] = vali
    return response

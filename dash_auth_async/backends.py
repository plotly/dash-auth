"""Framework adapters isolating Flask/Quart-specific request and session I/O."""

from __future__ import annotations

import inspect
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, MutableMapping
from contextvars import ContextVar
from typing import Any
from weakref import WeakKeyDictionary

import flask

try:
    import quart

    HAS_QUART = True
except ImportError:
    quart: Any = None
    HAS_QUART = False

try:
    import fastapi
    from starlette.middleware.sessions import SessionMiddleware
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import (
        HTMLResponse,
        PlainTextResponse,
        RedirectResponse,
        Response as StarletteResponse,
    )

    HAS_FASTAPI = True
except ImportError:
    fastapi: Any = None
    StarletteRequest: Any = None
    SessionMiddleware: Any = None
    HAS_FASTAPI = False


# dash-auth-async owns its own request ContextVar, set in its own ASGI
# middleware — independent of Dash's private get_current_request.
_current_request_var: ContextVar = ContextVar("dash_auth_request", default=None)


def _parse_callback_body(raw: bytes | str, content_encoding: str) -> Any:
    """Parse a callback request body exactly as Dash's dispatch will.

    The renderer gzips large payloads (``compress_payload``) and Dash inflates
    them when ``"gzip"`` is in ``Content-Encoding``; parsing the raw bytes
    instead saw no body and refused even logged-in users. Uses Dash's own
    decompressor (size-capped against gzip bombs).

    Returns:
        The parsed JSON, or None when it cannot be parsed (the caller fails
        closed).
    """
    try:
        if "gzip" in content_encoding:
            from dash._compression import (  # noqa: PLC0415, PLC2701 — dash>=4.x only
                decompress_payload,
            )

            return decompress_payload(raw if isinstance(raw, bytes) else raw.encode())
        return json.loads(raw) if raw else None
    except Exception:  # unparseable (or dash without compression) == no body
        return None


def _set_dash_request(request: Any) -> Any:
    """Populate Dash's FastAPI request ContextVar for the downstream call.

    Dash 4.3.0's ``DashMiddleware`` added a "pass-through to avoid consuming
    body stream" branch that returns *before* ``set_current_request`` for any
    non-``_dash-`` page route. Its catch-all then serves those routes via
    ``index()`` -> ``get_current_request()``, which raises "No active request
    in context" (a regression that breaks vanilla FastAPI page routes too).

    Our ``_AuthMiddleware`` runs *outside* ``DashMiddleware`` and already holds
    the request, so we set Dash's ContextVar ourselves and backfill the routes
    Dash abandoned. For routes Dash still handles, its own set/reset nests
    cleanly inside ours (ContextVar tokens are LIFO).

    Returns:
        A reset token to pass to :func:`_reset_dash_request`, or ``None`` if
        this Dash exposes no such helper (then it's a no-op).
    """
    try:
        from dash.backends._fastapi import (  # noqa: PLC0415, PLC2701 — lazy import of a Dash internal
            set_current_request,
        )
    except ImportError:
        return None
    return set_current_request(request)


def _reset_dash_request(token: Any) -> None:
    """Reset the Dash request ContextVar set by :func:`_set_dash_request`.

    No-op when ``token`` is ``None`` (the helper was unavailable).
    """
    if token is None:
        return
    from dash.backends._fastapi import (  # noqa: PLC0415, PLC2701 — lazy import of a Dash internal
        reset_current_request,
    )

    reset_current_request(token)


class Backend(ABC):
    """Framework adapter isolating everything Flask/Quart-specific.

    The auth decision logic is a pure function of (path, body); backends
    own the I/O around it: hook registration, body parsing, and the
    request/session proxies.
    """

    request: Any
    session: MutableMapping

    # Whether OIDC views must be async (awaited) on this backend. Lets
    # OIDCAuth pick the sync vs async view set polymorphically instead of
    # branching on isinstance(backend, ...).
    is_async: bool = False

    @abstractmethod
    def has_request_context(self) -> bool:
        """Whether a request context is currently active."""

    @abstractmethod
    def register_auth_hook(
        self,
        server,
        needs_body: Callable[[str], bool],
        decide: Callable[[str, dict | None], Any],
    ) -> None:
        """Register a before-request auth hook on the server.

        :param server: the Flask or Quart server instance
        :param needs_body: whether the JSON body must be parsed for this
            request path (evaluated per request)
        :param decide: pure decision function receiving
            (path, parsed_body_or_None); returns None to allow the request
            or a response value to short-circuit it
        """

    @abstractmethod
    def url_for(self, endpoint: str, **values) -> str:
        """Build a URL for the given endpoint on this backend."""

    @abstractmethod
    def redirect(self, location: str) -> Any:
        """Return a redirect response to the given location."""

    # --- Operations that diverge on FastAPI; defaults reproduce the
    # --- Flask/Quart behavior so those backends inherit unchanged. These
    # --- are concrete interface defaults, not all of which use `self`, so
    # --- PLR6301 (no-self-use) is suppressed where that applies.

    def coerce_response(self, result: Any) -> Any:  # noqa: PLR6301
        """Convert an ``_authorize`` return into a real response.

        Flask and Quart accept ``(body, status, headers)`` tuples, bare
        strings, and framework responses natively, so the default is a
        pass-through. FastAPI overrides this to build a Starlette response.

        Returns:
            The response value unchanged.
        """
        return result

    def setup_session(  # noqa: PLR6301
        self, server, secret_key: str | None, secure_session: bool = False
    ) -> None:
        """Install session support on the server.

        Flask/Quart store a ``secret_key`` attribute and harden the session
        cookie via ``SESSION_COOKIE_*`` config. FastAPI overrides this to add
        ``SessionMiddleware`` (and wires ``secure_session`` to ``https_only``).
        """
        if secret_key is not None:
            server.secret_key = secret_key
        if secure_session:
            server.config["SESSION_COOKIE_SECURE"] = True
            server.config["SESSION_COOKIE_HTTPONLY"] = True

    def session_configured(self, server) -> bool:  # noqa: PLR6301
        """Whether the server can store a session.

        Returns:
            True if a session secret is configured.
        """
        return getattr(server, "secret_key", None) is not None

    def current_host(self) -> str:
        """Host (netloc) of the active request, for proxy host rewrites.

        Returns:
            The request host string.
        """
        return self.request.host

    def current_path(self) -> str:
        """Path of the active request.

        Returns:
            The request path string.
        """
        return self.request.path

    def add_route(  # noqa: PLR6301
        self, server, rule: str, view_func, endpoint: str, methods
    ) -> None:
        """Register an OIDC route on the server."""
        server.add_url_rule(
            rule, endpoint=endpoint, view_func=view_func, methods=methods
        )

    def make_oauth(self, server) -> Any:  # noqa: PLR6301
        """Build the authlib OAuth registry for this backend.

        Returns:
            A flask_client ``OAuth`` registry bound to ``server``.
        """
        from authlib.integrations.flask_client import OAuth  # noqa: PLC0415

        return OAuth(server)

    def get_oauth(self, server) -> Any:  # noqa: PLR6301
        """Retrieve the authlib OAuth registry stored by :meth:`make_oauth`.

        Symmetric with ``make_oauth``: each backend knows where it put its own
        registry, so the module-level ``get_oauth`` doesn't have to guess.

        Returns:
            The registry, or None if ``OIDCAuth`` has not run yet.
        """
        return getattr(server, "extensions", {}).get(
            "authlib.integrations.flask_client"
        )

    def oauth_authorize_redirect(  # noqa: PLR6301
        self, client, redirect_uri: str, **kwargs
    ) -> Any:
        """Start the OAuth authorize-redirect on the authlib ``client``.

        Encapsulates how each backend's authlib client is invoked: the Flask
        client is synchronous and reads the request from a context global, so
        the default just calls through. Quart/FastAPI override to await, and
        FastAPI additionally passes the active request explicitly.

        Returns:
            The authorize-redirect response (awaitable on async backends).
        """
        return client.authorize_redirect(redirect_uri, **kwargs)

    def oauth_authorize_access_token(self, client, **kwargs) -> Any:  # noqa: PLR6301
        """Exchange the OAuth callback for a token on the authlib ``client``.

        Mirror of :meth:`oauth_authorize_redirect` for the callback leg.

        Returns:
            The token (awaitable on async backends).
        """
        return client.authorize_access_token(**kwargs)

    def store_config(self, server, key: str, value: Any) -> None:  # noqa: PLR6301
        """Stash an app-scoped config value (public routes/callbacks).

        Flask/Quart expose a dict-like ``server.config``. FastAPI has no
        such attribute and overrides this to use ``server.state``.
        """
        server.config[key] = value

    def read_config(  # noqa: PLR6301
        self, server, key: str, default: Any = None
    ) -> Any:
        """Read an app-scoped config value set by :meth:`store_config`.

        Returns:
            The stored value, or ``default`` when unset.
        """
        return server.config.get(key, default)

    def ws_identity(self, ws) -> tuple[Any, dict | None]:
        """Resolve ``(owning_server, session_user)`` for a WS callback_request.

        WS-capable backends override this. The owning server is the key into
        ``_AUTH_BY_SERVER``; the user is ``session["user"]`` or ``None``.
        Flask has no WebSocket transport, so the default raises -- the WS hook's
        fail-closed boundary turns that into a rejection if it is ever reached.

        Raises:
            NotImplementedError: on backends without WebSocket support.
        """
        raise NotImplementedError


class FlaskBackend(Backend):
    """Backend adapter for a Flask server."""

    # Properties, not class attributes: ABCMeta probes every namespace
    # value for __isabstractmethod__ at class creation, which unwraps
    # the context-local proxies outside any request and raises.
    @property
    def request(self) -> Any:
        """Flask's request context-local proxy.

        Returns:
            The Flask request proxy.
        """
        return flask.request

    @property
    def session(self) -> MutableMapping:
        """Flask's session mapping.

        Returns:
            The Flask session proxy.
        """
        return flask.session

    # The methods below are thin adapters over module-level framework
    # functions; they must stay instance methods to satisfy the Backend
    # interface, so PLR6301 (no-self-use) is suppressed on each.
    def has_request_context(self) -> bool:  # noqa: PLR6301
        """Whether a Flask request context is currently active.

        Returns:
            True if a request context is active.
        """
        return flask.has_request_context()

    def register_auth_hook(self, server, needs_body, decide) -> None:  # noqa: PLR6301
        """Register the before-request auth hook on a Flask server."""

        @server.before_request
        def before_request_auth():
            req = flask.request
            body = (
                _parse_callback_body(
                    req.get_data(cache=True), req.headers.get("Content-Encoding", "")
                )
                if needs_body(req.path)
                else None
            )
            return decide(flask.request.path, body)

    def url_for(self, endpoint: str, **values) -> str:  # noqa: PLR6301
        """Build a URL for a Flask endpoint.

        Returns:
            The URL string for ``endpoint``.
        """
        return flask.url_for(endpoint, **values)

    def redirect(self, location: str) -> Any:  # noqa: PLR6301
        """Build a Flask redirect response to ``location``.

        Returns:
            A Flask redirect response.
        """
        return flask.redirect(location)


class QuartBackend(Backend):
    """Backend adapter for a Quart (async) server."""

    is_async = True

    def __init__(self) -> None:
        """Create the Quart backend, requiring the optional ``quart`` extra.

        Raises:
            ImportError: if Quart is not installed.
        """
        if quart is None:
            raise ImportError(
                "Quart is not installed. Please install it with `pip install quart` "
                "or `pip install dash[quart]` to use the Quart backend."
            )

    @property
    def request(self) -> Any:
        """Quart's request context-local proxy.

        Returns:
            The Quart request proxy.
        """
        return quart.request

    @property
    def session(self) -> MutableMapping:
        """Quart's session mapping.

        Returns:
            The Quart session proxy.
        """
        return quart.session

    # The methods below are thin adapters over module-level framework
    # functions; they must stay instance methods to satisfy the Backend
    # interface, so PLR6301 (no-self-use) is suppressed on each.
    def has_request_context(self) -> bool:  # noqa: PLR6301
        """Whether a Quart request context is currently active.

        Returns:
            True if a request context is active.
        """
        return quart.has_request_context()

    def register_auth_hook(self, server, needs_body, decide) -> None:  # noqa: PLR6301
        """Register the before-request auth hook on a Quart server.

        Awaits both the request body and the (possibly coroutine) decision so
        async auth logic is preserved. Also mints the browser-stable
        ``dac_client`` cookie on first contact and, when a browser authenticates,
        retires its stale pre-login WebSocket so the renderer reconnects
        authenticated (see websocket_auth) -- the Quart half of Design A.
        """
        from .websocket_auth import (  # noqa: PLC0415 — avoid import cycle
            WS_CLIENT_COOKIE,
            close_anonymous_ws,
            mint_ws_client_id,
        )

        @server.before_request
        async def before_request_auth():
            req = quart.request
            body = (
                _parse_callback_body(
                    await req.get_data(cache=True),
                    req.headers.get("Content-Encoding", ""),
                )
                if needs_body(req.path)
                else None
            )
            result = decide(quart.request.path, body)
            if inspect.isawaitable(result):
                result = await result
            if result is not None:
                return result

            # Authorized. If this browser is now logged in, retire any stale
            # anonymous socket it opened before login so the renderer reconnects
            # authenticated before the first click.
            if quart.session.get("user") is not None:
                close_anonymous_ws(quart.request.cookies.get(WS_CLIENT_COOKIE))
            return None

        @server.after_request
        def set_client_cookie(response):
            # Minted on every response that lacks it -- including the BasicAuth
            # 401 challenge -- so it predates a later pre-login WS handshake.
            if quart.request.cookies.get(WS_CLIENT_COOKIE) is None:
                response.set_cookie(
                    WS_CLIENT_COOKIE,
                    mint_ws_client_id(),
                    httponly=True,
                    samesite="Lax",
                    path="/",
                )
            return response

    def url_for(self, endpoint: str, **values) -> str:  # noqa: PLR6301
        """Build a URL for a Quart endpoint.

        Returns:
            The URL string for ``endpoint``.
        """
        return quart.url_for(endpoint, **values)

    def redirect(self, location: str) -> Any:  # noqa: PLR6301
        """Build a Quart redirect response to ``location``.

        Returns:
            A Quart redirect response.
        """
        return quart.redirect(location)

    def make_oauth(self, server) -> Any:  # noqa: PLR6301
        """Build the authlib OAuth registry for the Quart backend.

        Returns:
            A custom Quart ``OAuth`` registry bound to ``server``.
        """
        # Imported lazily so flask-only installs never import quart/httpx.
        from dash_auth_async import quart_client  # noqa: PLC0415

        return quart_client.OAuth(server)

    def get_oauth(self, server) -> Any:  # noqa: PLR6301
        """Retrieve the Quart OAuth registry stored by :meth:`make_oauth`.

        Returns:
            The registry, or None if ``OIDCAuth`` has not run yet.
        """
        return getattr(server, "extensions", {}).get(
            "authlib.integrations.quart_client"
        )

    async def oauth_authorize_redirect(  # noqa: PLR6301
        self, client, redirect_uri: str, **kwargs
    ) -> Any:
        """Await the Quart authlib client's authorize-redirect.

        Returns:
            The authorize-redirect response.
        """
        return await client.authorize_redirect(redirect_uri, **kwargs)

    async def oauth_authorize_access_token(self, client, **kwargs) -> Any:  # noqa: PLR6301
        """Await the Quart authlib client's token exchange.

        Returns:
            The token.
        """
        return await client.authorize_access_token(**kwargs)

    def ws_identity(self, ws) -> tuple[Any, dict | None]:  # noqa: PLR6301
        """Resolve the Quart app and session user for a WS callback_request.

        Uses Quart's context globals (correct when several apps share a
        process); ``ws`` is unused on this backend.

        Returns:
            ``(quart_app, session["user"] or None)``.
        """
        import quart  # noqa: PLC0415 — quart is an optional dependency

        # ``quart.current_app`` is a proxy; ``_get_current_object`` unwraps it to
        # the real Quart app (the key in ``_AUTH_BY_SERVER``). Go through
        # ``getattr`` because the attribute is absent from the proxy's type stub.
        app = getattr(quart.current_app, "_get_current_object")()
        return app, quart.session.get("user")


class FastAPIBackend(Backend):
    """Adapter for Dash's FastAPI backend (Dash 4.2+).

    Unlike Flask/Quart there is no global request/session proxy: Starlette
    passes the request explicitly. This backend resolves the active request
    from a ContextVar set by its own ASGI auth middleware, and reads the
    session off ``request.session`` (populated by SessionMiddleware).
    """

    is_async = True

    def __init__(self) -> None:
        """Create the FastAPI backend, requiring the optional ``fastapi`` extra.

        Raises:
            ImportError: if FastAPI is not installed.
        """
        if not HAS_FASTAPI:
            raise ImportError(
                "FastAPI is not installed. Please install it with "
                "`pip install dash-auth-async[fastapi]` to use the FastAPI backend."
            )

    @property
    def request(self) -> Any:
        """The active Starlette request, resolved from the ContextVar.

        Returns:
            The current request, or None outside a request context.
        """
        return _current_request_var.get()

    @property
    def session(self) -> MutableMapping:
        """The session mapping off the active request.

        Returns:
            The Starlette session mapping.

        Raises:
            RuntimeError: if SessionMiddleware is not installed.
        """
        # Starlette signals "no SessionMiddleware" via a bare `assert
        # "session" in scope`, which `python -O` strips — the next line then
        # raises KeyError instead. Check the scope directly so the
        # RuntimeError translation holds under -O too, keeping the existing
        # `except RuntimeError` guards working identically to the Flask path.
        request = self.request
        if "session" not in getattr(request, "scope", {}):
            raise RuntimeError("Session is not available. Have you set a secret key?")
        return request.session

    def has_request_context(self) -> bool:  # noqa: PLR6301
        """Whether a request is currently bound to the ContextVar.

        Returns:
            True if a request context is active.
        """
        return _current_request_var.get() is not None

    def url_for(self, endpoint: str, **values) -> str:
        """Build an absolute URL for a Starlette endpoint.

        Maps the Flask-style ``_external``/``_scheme`` kwargs used by
        ``OIDCAuth._create_redirect_uri`` onto Starlette's ``url_for``.

        Returns:
            The URL string for ``endpoint``.
        """
        values.pop("_external", None)  # Starlette url_for is always absolute
        scheme = values.pop("_scheme", None)
        url = self.request.url_for(endpoint, **values)
        if scheme:
            url = url.replace(scheme=scheme)
        return str(url)

    def redirect(self, location: str) -> Any:  # noqa: PLR6301
        """Build a Starlette redirect response to ``location``.

        Returns:
            A 302 ``RedirectResponse``.
        """
        return RedirectResponse(location, status_code=302)

    def current_host(self) -> str:
        """Host (netloc) of the active request.

        Returns:
            The request netloc string.
        """
        return self.request.url.netloc

    def current_path(self) -> str:
        """Path of the active Starlette request.

        Returns:
            The request path string.
        """
        return self.request.url.path

    def coerce_response(self, result: Any) -> Any:  # noqa: PLR6301
        """Build a Starlette response from an ``_authorize``/view return value.

        This is the single coercion boundary for the FastAPI path: every OIDC
        view and the auth middleware funnel their return value through here, so
        the framework-response knowledge lives in exactly one place.

        A bare ``str`` becomes an ``HTMLResponse`` (matching Flask/Quart, which
        render returned strings as ``text/html`` — e.g. the OIDC logout page),
        while ``(body, status[, headers])`` tuples become a ``PlainTextResponse``
        carrying the status/headers (e.g. the Basic-auth 401 challenge).

        Returns:
            A Starlette response (passthrough if already one).
        """
        if isinstance(result, StarletteResponse):
            return result
        if isinstance(result, tuple):
            body, *rest = result
            status = rest[0] if rest else 200
            headers = rest[1] if len(rest) > 1 else None
            return PlainTextResponse(body, status_code=status, headers=headers)
        if isinstance(result, str):
            return HTMLResponse(result)
        return PlainTextResponse(str(result))

    @staticmethod
    def _session_middleware(server) -> Any:
        return next(
            (
                m
                for m in getattr(server, "user_middleware", [])
                if getattr(m, "cls", None) is SessionMiddleware
            ),
            None,
        )

    def _has_session_middleware(self, server) -> bool:
        return self._session_middleware(server) is not None

    def setup_session(
        self, server, secret_key: str | None, secure_session: bool = False
    ) -> None:
        """Install Starlette ``SessionMiddleware`` from ``secret_key``.

        ``secure_session`` is wired to ``https_only`` so the parity with
        Flask/Quart's ``SESSION_COOKIE_SECURE`` is honored rather than
        silently dropped. Starlette always sets ``HttpOnly``. Defers to a
        user-installed ``SessionMiddleware`` (opt-out/override) and is
        idempotent — never adds a second instance.

        Either way the session middleware ends up *outermost*: the auth
        middleware reads ``request.session``, so one the user installed before
        ``Auth(...)`` (which would sit inside the auth middleware, leaving the
        session unreadable there) is hoisted to the front of the stack.
        """
        existing = self._session_middleware(server)
        if existing is not None:
            server.user_middleware.remove(existing)
            server.user_middleware.insert(0, existing)
            return
        if secret_key is None:
            return
        server.add_middleware(
            SessionMiddleware, secret_key=secret_key, https_only=secure_session
        )

    def session_configured(self, server) -> bool:
        """Whether a ``SessionMiddleware`` is installed on the server.

        Returns:
            True if session storage is available.
        """
        return self._has_session_middleware(server)

    def store_config(self, server, key: str, value: Any) -> None:  # noqa: PLR6301
        """Stash an app-scoped config value on the FastAPI ``server.state``."""
        setattr(server.state, key, value)

    def read_config(  # noqa: PLR6301
        self, server, key: str, default: Any = None
    ) -> Any:
        """Read an app-scoped config value off the FastAPI ``server.state``.

        Returns:
            The stored value, or ``default`` when unset.
        """
        return getattr(server.state, key, default)

    def add_route(  # noqa: PLR6301
        self, server, rule: str, view_func, endpoint: str, methods
    ) -> None:
        """Register an OIDC route, translating Flask ``<idp>`` to ``{idp}``."""
        fastapi_rule = re.sub(r"<([^>]+)>", r"{\1}", rule)
        server.add_api_route(
            fastapi_rule,
            view_func,
            methods=methods,
            name=endpoint,
            include_in_schema=False,
        )

    def make_oauth(self, server) -> Any:  # noqa: PLR6301
        """Build authlib's Starlette OAuth registry, stashed on ``server.state``.

        Returns:
            A ``starlette_client`` ``OAuth`` registry.
        """
        from authlib.integrations.starlette_client import (  # noqa: PLC0415
            OAuth as StarletteOAuth,
        )

        oauth = StarletteOAuth()
        # The Starlette registry doesn't attach to app.extensions, so stash
        # it where get_oauth can find it.
        server.state.dash_auth_oauth = oauth
        return oauth

    def get_oauth(self, server) -> Any:  # noqa: PLR6301
        """Retrieve the Starlette OAuth registry stashed on ``server.state``.

        Returns:
            The registry, or None if ``OIDCAuth`` has not run yet.
        """
        return getattr(getattr(server, "state", None), "dash_auth_oauth", None)

    async def oauth_authorize_redirect(
        self, client, redirect_uri: str, **kwargs
    ) -> Any:
        """Await the Starlette authlib client's authorize-redirect.

        The Starlette OAuth client takes the request explicitly (no context
        global), so the active request is resolved from the ContextVar and
        passed through.

        Returns:
            The authorize-redirect response.
        """
        return await client.authorize_redirect(self.request, redirect_uri, **kwargs)

    async def oauth_authorize_access_token(self, client, **kwargs) -> Any:
        """Await the Starlette authlib client's token exchange.

        Passes the ContextVar-resolved request, as the Starlette client
        requires.

        Returns:
            The token.
        """
        return await client.authorize_access_token(self.request, **kwargs)

    def ws_identity(self, ws) -> tuple[Any, dict | None]:  # noqa: PLR6301
        """Resolve the FastAPI app and session user for a WS callback_request.

        Reads from the Starlette ``WebSocket``: ``ws.app`` is the owning server
        and ``ws.session`` carries ``session["user"]`` (SessionMiddleware runs on
        websocket scopes, so the handshake cookie is available). The
        ``"session" in ws.scope`` guard mirrors the ``session`` property: with no
        SessionMiddleware installed the user is ``None`` (fail-closed for
        protected callbacks, still allows public) rather than raising.

        Returns:
            ``(fastapi_app, session["user"] or None)``.
        """
        user = ws.session.get("user") if "session" in ws.scope else None
        return ws.app, user

    def register_auth_hook(self, server, needs_body, decide) -> None:
        """Register the before-request auth hook as pure-ASGI middleware.

        Pure ASGI (not ``BaseHTTPMiddleware``) so the request ContextVar set
        here is visible inside the Dash callback, which runs in the same
        task/context via the inner DashMiddleware's ``copy_context()``.
        """
        backend = self

        class _AuthMiddleware:
            def __init__(self, app) -> None:
                self.app = app

            async def __call__(self, scope, receive, send) -> None:
                if scope["type"] != "http":
                    await self.app(scope, receive, send)
                    return

                request = StarletteRequest(scope, receive)
                token = _current_request_var.set(request)

                # Browser-stable client id, minted on first contact so it is
                # already present at a later pre-login WS handshake. This ties an
                # anonymous socket back to the browser that authenticates here,
                # letting login retire the stale socket (see websocket_auth).
                from .websocket_auth import (  # noqa: PLC0415 — avoid import cycle
                    WS_CLIENT_COOKIE,
                    close_anonymous_ws,
                    mint_ws_client_id,
                )

                client_id = request.cookies.get(WS_CLIENT_COOKIE)
                set_client_cookie = client_id is None
                if set_client_cookie:
                    client_id = mint_ws_client_id()

                async def send(message, _send=send):
                    if set_client_cookie and message["type"] == "http.response.start":
                        message.setdefault("headers", []).append(
                            (
                                b"set-cookie",
                                f"{WS_CLIENT_COOKIE}={client_id}; Path=/; "
                                f"HttpOnly; SameSite=Lax".encode("latin-1"),
                            )
                        )
                    await _send(message)

                try:
                    body = None
                    downstream_receive = receive
                    if needs_body(request.url.path):
                        # Consuming the body drains the receive stream; cache
                        # the bytes and replay them so DashMiddleware (inner)
                        # can re-parse the callback JSON.
                        raw = await request.body()
                        body_replayed = False

                        async def downstream_receive():
                            nonlocal body_replayed
                            if body_replayed:
                                # Body already delivered (and drained from the
                                # real stream), so the real receive() now blocks
                                # until the client actually disconnects. Faking
                                # a disconnect here made StreamingResponse's
                                # disconnect listener cancel every stream.
                                # A second body read past this point therefore
                                # waits for the disconnect instead of failing
                                # fast; nothing downstream re-reads the body.
                                return await receive()
                            body_replayed = True
                            return {
                                "type": "http.request",
                                "body": raw,
                                "more_body": False,
                            }

                        body = _parse_callback_body(
                            raw, request.headers.get("content-encoding", "")
                        )

                    result = decide(request.url.path, body)
                    if inspect.isawaitable(result):
                        result = await result

                    if result is not None:
                        response = backend.coerce_response(result)
                        await response(scope, receive, send)
                        return

                    # Authorized. If this browser is now logged in, retire any
                    # stale anonymous sockets it opened before login so the
                    # renderer reconnects authenticated before the first click.
                    try:
                        logged_in = backend.session.get("user") is not None
                    except RuntimeError:
                        logged_in = False  # no SessionMiddleware -> nothing to retire
                    if logged_in:
                        close_anonymous_ws(client_id)

                    # Backfill Dash's request ContextVar so the catch-all's
                    # index() works on Dash 4.3.0, which skips it for page
                    # routes (see _set_dash_request).
                    dash_token = _set_dash_request(request)
                    try:
                        await self.app(scope, downstream_receive, send)
                    finally:
                        _reset_dash_request(dash_token)
                finally:
                    _current_request_var.reset(token)

        server.add_middleware(_AuthMiddleware)


# server -> the backend its ``Auth`` was constructed with. Helpers that only
# hold the server (public routes/callbacks, ``get_oauth``) resolve through
# ``detect_backend``, which must hand back an explicitly passed custom backend
# rather than re-detecting by server type. Weak keys so test apps are collected.
_BACKEND_BY_SERVER: WeakKeyDictionary[Any, Backend] = WeakKeyDictionary()
# Fallback for servers that can't be weakly referenced (e.g. ``__slots__``),
# keyed by ``id``; holding the server keeps its id from being reused.
_BACKEND_BY_SERVER_ID: dict[int, tuple[Any, Backend]] = {}


def register_backend(server: Any, backend: Backend) -> None:
    """Record ``backend`` as the one serving ``server`` (see ``detect_backend``)."""
    try:
        _BACKEND_BY_SERVER[server] = backend
    except TypeError:  # not weakly referenceable
        _BACKEND_BY_SERVER_ID[id(server)] = (server, backend)


def _registered_backend(server: Any) -> Backend | None:
    try:
        return _BACKEND_BY_SERVER.get(server)
    except TypeError:  # not weakly referenceable
        entry = _BACKEND_BY_SERVER_ID.get(id(server))
        return entry[1] if entry is not None and entry[0] is server else None


def detect_backend(server: Any) -> Backend:
    """Return the backend for a server.

    The backend registered for it by ``Auth.__init__`` if any, otherwise the
    one matching a Flask, Quart, or FastAPI server type.
    """
    registered = _registered_backend(server)
    if registered is not None:
        return registered
    if quart is not None:
        if isinstance(server, quart.Quart):
            return QuartBackend()
    if HAS_FASTAPI and isinstance(server, fastapi.FastAPI):
        return FastAPIBackend()
    if isinstance(server, flask.Flask):
        return FlaskBackend()

    raise NotImplementedError(
        f"No backend implemented for server type {type(server)}. "
        "If you are using a custom server, please provide a custom Backend "
        "instance to Auth(..., backend=MyBackend())."
    )


# One backend per process, matching how Dash apps are deployed.
_active_backend: Backend | None = None


def set_active_backend(backend: Backend) -> None:
    """Register the backend used by request-context helpers.

    Called by Auth.__init__; group_protection functions run inside Dash
    callbacks with no auth instance in scope and look the backend up here.
    """
    global _active_backend  # noqa: PLW0603 — one backend per process, by design
    _active_backend = backend


def get_active_backend() -> Backend:
    """Return the active backend registered by ``Auth.__init__``.

    Falls back to a Flask backend for the legacy Flask-only path where no
    ``Auth`` has registered one yet. The fallback is constructed lazily on
    first use rather than at import, so Flask isn't cemented as the default
    at module load. Note this still assumes a single backend per process: in
    a non-Flask process the active backend must be set (which ``Auth.__init__``
    does) before any request-context helper runs.
    """
    global _active_backend  # noqa: PLW0603 — one backend per process, by design
    if _active_backend is None:
        _active_backend = FlaskBackend()
    return _active_backend

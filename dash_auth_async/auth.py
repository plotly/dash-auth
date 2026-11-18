"""Framework-agnostic authentication base class for Dash."""

from abc import ABC, abstractmethod

from dash import Dash

# Dash's pre-setup callback registry; no public API equivalent exists.
from dash._callback import GLOBAL_CALLBACK_MAP  # noqa: PLC2701

from .backends import (
    Backend,
    detect_backend,
    register_backend,
    set_active_backend,
)
from .group_protection import background_gate_response, has_background_gate
from .public_routes import (
    add_public_routes,
    get_public_callbacks,
    get_public_routes,
    get_url_base,
)
from .websocket_auth import enable_ws_auth


class Auth(ABC):
    """Base class holding the framework-agnostic auth decision logic."""

    def __init__(
        self,
        app: Dash,
        public_routes: list | None = None,
        backend: Backend | None = None,
        **obsolete,
    ):
        """Auth base class for authentication in Dash.

        :param app: Dash app
        :param public_routes: list of public routes, routes should follow the
            Flask route syntax
        :param backend: framework adapter to use. ``None`` (default) detects it
            from the server type; pass a custom ``Backend`` for a server that
            is not Flask, Quart or FastAPI.

        Raises:
            TypeError: if any deprecated/unexpected keyword argument is passed.
        """
        # Deprecated arguments
        if obsolete:
            raise TypeError(f"Auth got unexpected keyword arguments: {list(obsolete)}")

        self.app = app
        self.backend = backend if backend is not None else detect_backend(app.server)
        register_backend(app.server, self.backend)
        set_active_backend(self.backend)
        self._protect()
        if public_routes is not None:
            add_public_routes(app, public_routes)
        enable_ws_auth(self, app)

    @property
    def request(self):
        """The active backend's request proxy.

        Returns:
            The framework-specific request object for the current request.
        """
        return self.backend.request

    @property
    def session(self):
        """The active backend's session proxy.

        Returns:
            The framework-specific session mapping for the current request.
        """
        return self.backend.session

    def _callback_path(self) -> str:
        """Path of Dash's callback route, including any URL base prefix.

        Returns:
            The fully-qualified ``_dash-update-component`` path.
        """
        url_base = get_url_base(self.app)
        return f"{url_base.rstrip('/')}/_dash-update-component"

    def _protect(self):
        """Add a before_request authentication check on all routes.

        The authentication check will pass if either
            * The endpoint is marked as public via `add_public_routes`
            * The request is authorised by `Auth.is_authorised`
        """
        self.backend.register_auth_hook(
            self.app.server,
            lambda path: path == self._callback_path(),
            self._authorize,
        )

    def _authorize(self, path: str, body: dict | None):
        """Decide whether a request may proceed.

        Pure decision logic shared by all backends: receives the request
        path and the parsed JSON body (only provided for the Dash callback
        route).

        Returns:
            None to allow the request, or a login response to reject it.
        """
        public_routes = get_public_routes(self.app)
        public_callbacks = get_public_callbacks(self.app)
        if path == self._callback_path():
            # Treat a missing, unparseable or non-object body (valid JSON
            # that is a list/string/number) as unauthorised rather than
            # crashing with AttributeError/KeyError → 500.
            if not body or not isinstance(body, dict):
                return self.login_request()

            # Check whether the callback is marked as public
            if body.get("output") in public_callbacks:
                return None

            # A routing callback (one registered with a pathname input) is
            # public when that pathname hits a public route
            if self._is_public_routing_callback(body):
                return None

        # If the route is not a callback route, check whether the path
        # matches a public route, or whether the request is authorised
        if public_routes.test(path) or self.is_authorized():
            if path == self._callback_path():
                # Group-protected background callbacks are gated here, not in
                # their job process (which has no session to read).
                return background_gate_response(self.app, body)
            return None

        # Otherwise, ask the user to log in
        return self.login_request()

    def authorize_ws(self, payload: dict | None, user: dict | None) -> bool:
        """Decide whether a WebSocket callback_request may run.

        Mirrors ``_authorize``'s public checks but, because there is no
        ``request`` context over a WebSocket, treats the presence of an
        authenticated session user as proof of login (the session cookie sent
        at the handshake already proves it).

        :param payload: the callback payload (same shape as the HTTP
            ``_dash-update-component`` body: ``output``, ``inputs``, ...)
        :param user: ``session["user"]`` or ``None``

        Returns:
            True to allow the callback, False to reject the connection.
        """
        payload = payload or {}
        public_callbacks = get_public_callbacks(self.app)
        if payload.get("output") in public_callbacks:
            return True

        if self._is_public_routing_callback(payload):
            return True

        # A group-protected background callback's job is registered ungated
        # (its gate runs in _authorize, over HTTP). The renderer never sends
        # background callbacks over the socket, so refuse them here rather
        # than let a crafted message run the job without the group check.
        if has_background_gate(self.app, payload.get("output")):
            return False

        return user is not None

    def _is_public_routing_callback(self, body: dict) -> bool:
        """Whether ``body`` invokes a routing callback on a public pathname.

        Which arguments are pathnames is read from the *registered* callback,
        never from the request: the body's own ``property`` labels are
        client-controlled, and Dash only validates the argument count. Trusting
        them let any callback be invoked unauthenticated by relabelling one
        input as ``pathname`` with a public-route value.

        Returns:
            True if the callback declares pathname inputs and every value the
            request supplies for them matches a public route.
        """
        output = body.get("output")
        if not isinstance(output, str):
            return False
        # Callbacks sit in Dash's global map until its first-request setup
        # migrates them onto the app, which may not have run yet.
        spec = self.app.callback_map.get(output) or GLOBAL_CALLBACK_MAP.get(output)
        if not spec:
            return False

        # Dash builds the callback arguments positionally from inputs + state,
        # so index the same flat list to see exactly what the callback receives.
        inputs, state = body.get("inputs"), body.get("state")
        args = [
            *(inputs if isinstance(inputs, list) else []),
            *(state if isinstance(state, list) else []),
        ]
        pathnames = [
            args[i].get("value")
            if i < len(args) and isinstance(args[i], dict)
            else None
            for i, dep in enumerate(spec["inputs"])
            if dep.get("property") == "pathname"
        ]
        public_routes = get_public_routes(self.app)
        return bool(pathnames) and all(
            isinstance(p, str) and p and public_routes.test(p) for p in pathnames
        )

    @abstractmethod
    def is_authorized(self):
        """Return whether the current request is authenticated."""

    @abstractmethod
    def login_request(self):
        """Return the response that challenges an unauthenticated client."""

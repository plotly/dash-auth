"""OpenID Connect authentication for Dash on Flask and Quart backends."""

import logging
import os
import re
from html import escape
from typing import TYPE_CHECKING

import dash
from authlib.integrations.base_client import OAuthError
from authlib.integrations.flask_client import OAuth
from flask import Response
from werkzeug.routing import Map, Rule

from dash_auth_async.auth import Auth
from dash_auth_async.public_routes import get_url_base

from .backends import Backend, detect_backend
from .stream_revocation import (
    SESSION_ID_KEY,
    ensure_session_id,
    revoke_session_streams,
)
from .websocket_auth import WS_CLIENT_COOKIE, close_authenticated_ws

if TYPE_CHECKING:
    from authlib.integrations.flask_client.apps import (
        FlaskOAuth1App,
        FlaskOAuth2App,
    )

    from dash_auth_async.quart_client import OAuth as QuartOAuth, QuartOAuth2App


class OIDCAuth(Auth):
    """Implements auth via OpenID."""

    def __init__(  # noqa: PLR0913, PLR0917 — configuration constructor
        self,
        app: dash.Dash,
        secret_key: str | None = None,
        force_https_callback: bool | str | None = None,
        login_route: str = "/oidc/<idp>/login",
        logout_route: str = "/oidc/logout",
        callback_route: str = "/oidc/<idp>/callback",
        idp_selection_route: str | None = None,
        log_signins: bool = False,
        public_routes: list | None = None,
        logout_page: str | Response | None = None,
        secure_session: bool = False,
        backend: Backend | None = None,
    ):
        """Secure a Dash app through OpenID Connect.

        Parameters
        ----------
        app : Dash
            The Dash app to secure
        secret_key : str, optional
            A string to protect the Flask session, by default None.
            Generate a secret key in your Python session
            with the following commands:
            >>> import os
            >>> import base64
            >>> base64.b64encode(os.urandom(30)).decode('utf-8')
            Note that you should not do this dynamically:
            you should create a key and then assign the value of
            that key in your code.
        force_https_callback : Union[bool, str], optional
            Whether to force redirection to https, by default None
            This is useful when the HTTPS termination is upstream of the server
            If a string is passed, this will check for the existence of
            an envvar with that name and force https callback if it exists.
        login_route : str, optional
            The route for the login function, it requires a <idp>
            placeholder, by default "/oidc/<idp>/login".
        logout_route : str, optional
            The route for the logout function, by default "/oidc/logout".
        callback_route : str, optional
            The route for the OIDC redirect URI, it requires a <idp>
            placeholder, by default "/oidc/<idp>/callback".

            NOTE: login_route, logout_route, and callback_route are
            registered directly on the Flask server at the paths given here,
            regardless of any ``url_base_pathname`` or
            ``routes_pathname_prefix`` set on the Dash app. If your app is
            deployed under a prefix (e.g. ``url_base_pathname="/app/"``), the
            OIDC routes still live at the server root (e.g.
            ``/oidc/<idp>/callback``), NOT under the prefix. Configure your
            IDP's redirect URI accordingly.
        idp_selection_route : str, optional
            The route for the IDP selection function, by default None
        log_signins : bool, optional
            Whether to log signins, by default False
        public_routes : list, optional
            List of public routes, routes should follow the
            Flask route syntax
        logout_page : str or Response, optional
            Page seen by the user after logging out,
            by default None which will default to a simple logged out message
        secure_session: bool, optional
            Whether to restrict the session cookie to HTTPS, by default False.
            On Flask/Quart this sets SESSION_COOKIE_SECURE and
            SESSION_COOKIE_HTTPONLY; on FastAPI it sets the Starlette
            SessionMiddleware ``https_only`` flag (HttpOnly is always on).
        backend : Backend, optional
            Framework adapter to use, by default None (detected from the
            server type).

        Raises:
            RuntimeError: if ``app.server.secret_key`` is not defined.
            Exception: if the login or callback route lacks an ``<idp>``
                placeholder.
        """
        super().__init__(app, public_routes=public_routes, backend=backend)

        if isinstance(force_https_callback, str):
            self.force_https_callback = force_https_callback in os.environ
        elif force_https_callback is not None:
            self.force_https_callback = force_https_callback
        else:
            self.force_https_callback = False

        self.login_route = login_route
        self.logout_route = logout_route
        self.callback_route = callback_route
        self.log_signins = log_signins
        self.idp_selection_route = idp_selection_route
        self.logout_page = logout_page

        self.backend.setup_session(app.server, secret_key, secure_session)

        if not self.backend.session_configured(app.server):
            raise RuntimeError("""
                app.server.secret_key is missing.
                Generate a secret key in your Python session
                with the following commands:
                >>> import os
                >>> import base64
                >>> base64.b64encode(os.urandom(30)).decode('utf-8')
                and assign it to the property app.server.secret_key
                (where app is your dash app instance), or pass is as
                the secret_key argument to OIDCAuth.__init__.
                Note that you should not do this dynamically:
                you should create a key and then assign the value of
                that key in your code/via a secret.
                """)

        self.oauth = self.backend.make_oauth(app.server)

        # Check that the login and callback rules have an <idp> placeholder
        if not re.findall(r"/<idp>(?=/|$)", login_route):
            raise Exception("The login route must contain a <idp> placeholder.")
        if not re.findall(r"/<idp>(?=/|$)", callback_route):
            raise Exception("The callback route must contain a <idp> placeholder.")

        if self.backend.is_async:
            login_view = self._login_request_async
            logout_view = self._logout_async
            callback_view = self._callback_async
        else:
            login_view = self.login_request
            logout_view = self.logout
            callback_view = self.callback

        self.backend.add_route(
            app.server, login_route, login_view, "oidc_login", ["GET"]
        )
        self.backend.add_route(
            app.server, logout_route, logout_view, "oidc_logout", ["GET"]
        )
        self.backend.add_route(
            app.server, callback_route, callback_view, "oidc_callback", ["GET"]
        )

    def register_provider(self, idp_name: str, **kwargs):
        """Register an OpenID Connect provider.

        :param idp_name: The name of the provider
        :param kwargs: Keyword arguments passed to OAuth.register.
            See https://docs.authlib.org/en/latest/client/flask.html for
            additional details.
            Typical keyword arguments for OIDC include:
            * client_id
            * client_secret
            * server_metadata_url
            * token_endpoint_auth_method
            * client_kwargs (defaults to {"scope": "openid email"})

        Raises:
            ValueError: if ``idp_name`` contains unsupported characters.
        """
        if not re.match(r"^[\w\-\. ]+$", idp_name):
            raise ValueError(
                "`idp_name` should only contain letters, numbers, hyphens, "
                "underscores, periods and spaces"
            )
        client_kwargs = kwargs.pop("client_kwargs", {})
        client_kwargs.setdefault("scope", "openid email")
        self.oauth.register(idp_name, client_kwargs=client_kwargs, **kwargs)

    def get_oauth_client(self, idp: str):
        """Get the OAuth client.

        Returns:
            The authlib OAuth client for the given idp.

        Raises:
            ValueError: if ``idp`` is not a registered provider.
        """
        if idp not in self.oauth._registry:
            raise ValueError(f"'{idp}' is not a valid registered idp")

        client: FlaskOAuth1App | FlaskOAuth2App | QuartOAuth2App = (
            self.oauth.create_client(idp)
        )
        return client

    def get_oauth_kwargs(self, idp: str):
        """Get the OAuth kwargs.

        Returns:
            The registration kwargs stored for the given idp.

        Raises:
            ValueError: if ``idp`` is not a registered provider.
        """
        if idp not in self.oauth._registry:
            raise ValueError(f"'{idp}' is not a valid registered idp")

        kwargs: dict = self.oauth._registry[idp][1]
        return kwargs

    def _resolve_idp(self, idp: str | None):
        """Resolve which idp to use for login.

        Shared by the sync and async login views so selection behavior
        cannot drift.

        Returns:
            ``(idp, None)`` when a provider could be determined, or
            ``(None, response)`` when the caller should return ``response``
            instead (idp-selection redirect or a 400).
        """
        if idp in self.oauth._registry:
            return idp, None
        # If only one provider is registered, we don't need to
        # ask the user to pick one, just use the one
        if len(self.oauth._registry) == 1:
            return next(iter(self.oauth._registry)), None
        # If there are several providers and a `idp_selection_route`
        # was provided, redirect to it.
        if self.idp_selection_route:
            return None, self.backend.redirect(self.idp_selection_route)
        return None, (
            "Several OAuth providers are registered. Please choose one.",
            400,
        )

    def _create_redirect_uri(self, idp: str):
        """Create the redirect uri based on callback endpoint and idp.

        Host and scheme come from the request scope only. Behind a proxy,
        configure the WSGI/ASGI server to populate them from forwarded headers
        (werkzeug ``ProxyFix`` / hypercorn ``--forwarded-allow-ips``) — the
        library must never trust a client-supplied ``X-Forwarded-Host`` to
        build the IdP ``redirect_uri`` (auth-code leak / open redirect).
        ``force_https_callback`` covers the scheme half of dash-auth#154.

        Returns:
            The fully-qualified OIDC callback redirect URI.
        """
        if self.force_https_callback:
            return self.backend.url_for(
                "oidc_callback", idp=idp, _external=True, _scheme="https"
            )
        return self.backend.url_for("oidc_callback", idp=idp, _external=True)

    def login_request(self, idp: str | None = None):
        """Start the login process.

        On the Quart path this returns a coroutine (both the route and the
        before-request hook await it); on Flask it returns the response.

        Returns:
            The authorize-redirect response, or a coroutine producing it on
            the Quart path.
        """
        # `idp` can be none here as login_request is called
        # without arguments in the before_request hook
        if self.backend.is_async:
            # Returns a coroutine; the async before-request hook / route awaits it.
            return self._login_request_async(idp)

        idp, response = self._resolve_idp(idp)
        if response is not None:
            return response

        redirect_uri = self._create_redirect_uri(idp)
        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        return self.backend.oauth_authorize_redirect(
            oauth_client,
            redirect_uri,
            **oauth_kwargs.get("authorize_redirect_kwargs", {}),
        )

    async def _login_request_async(self, idp: str | None = None):
        """Async login view shared by the Quart and FastAPI paths.

        Backend-agnostic: the backend supplies the (possibly request-injecting)
        authlib call and coerces the result to a framework response.

        Returns:
            The authorize-redirect response.
        """
        idp, response = self._resolve_idp(idp)
        if response is not None:
            return self.backend.coerce_response(response)

        redirect_uri = self._create_redirect_uri(idp)
        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        result = await self.backend.oauth_authorize_redirect(
            oauth_client,
            redirect_uri,
            **oauth_kwargs.get("authorize_redirect_kwargs", {}),
        )
        return self.backend.coerce_response(result)

    def logout(self):  # pylint: disable=C0116
        """Logout the user.

        Returns:
            The logged-out page content.
        """
        # The open socket's user is a handshake-time snapshot the cleared
        # session can't reach: retire it so the logout applies there too.
        close_authenticated_ws(self.request.cookies.get(WS_CLIENT_COOKIE))
        # Same for protected HTTP streams the session started: their user is
        # captured at dispatch, so mark the session id revoked for them to see.
        revoke_session_streams(self.app, self.session.get(SESSION_ID_KEY))
        self.session.clear()
        base_url = get_url_base(self.app) or "/"
        page = (
            self.logout_page
            or f"""
        <div style="display: flex; flex-direction: column;
        gap: 0.75rem; padding: 3rem 5rem;">
            <div>Logged out successfully</div>
            <div><a href="{base_url}">Go back</a></div>
        </div>
        """
        )
        return page

    async def _logout_async(self):
        """Async logout view shared by the Quart and FastAPI paths.

        The body is sync; the backend coerces the HTML page to a framework
        response (passthrough on Quart, ``HTMLResponse`` on FastAPI).

        Returns:
            The logged-out page response.
        """
        return self.backend.coerce_response(self.logout())

    def callback(self, idp: str):  # pylint: disable=C0116
        """Handle the OIDC dance and post-login actions.

        Returns:
            The post-login redirect, or an error tuple on failure.
        """
        # `idp` and the IdP error text are request-controlled and Flask/Quart
        # render a returned str as text/html: escape them (reflected XSS).
        if idp not in self.oauth._registry:
            return f"'{escape(idp)}' is not a valid registered idp", 400

        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        try:
            token = self.backend.oauth_authorize_access_token(
                oauth_client,
                **oauth_kwargs.get("authorize_token_kwargs", {}),
            )
        except OAuthError as err:
            return escape(str(err)), 401

        user = token.get("userinfo")
        return self.after_logged_in(user, idp, token)

    async def _callback_async(self, idp: str):
        """Async OIDC callback view shared by the Quart and FastAPI paths.

        Backend-agnostic: the backend supplies the (possibly request-injecting)
        token exchange and coerces every return through the single boundary.

        Returns:
            The post-login redirect, or an error response on failure.
        """
        if idp not in self.oauth._registry:
            return self.backend.coerce_response(
                (f"'{escape(idp)}' is not a valid registered idp", 400)
            )

        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        try:
            token = await self.backend.oauth_authorize_access_token(
                oauth_client,
                **oauth_kwargs.get("authorize_token_kwargs", {}),
            )
        except OAuthError as err:
            return self.backend.coerce_response((escape(str(err)), 401))

        user = token.get("userinfo")
        return self.backend.coerce_response(self.after_logged_in(user, idp, token))

    def after_logged_in(self, user: dict | None, idp: str, token: dict):
        """Run post-login actions after successful OIDC authentication.

        For example, allows passing custom attributes to the user session::

            class MyOIDCAuth(OIDCAuth):
                def after_logged_in(self, user, idp, token):
                    if user:
                        user["params"] = value1
                    return super().after_logged_in(user, idp, token)

        Returns:
            A redirect response to the app's base URL.
        """
        if user:
            self.session["user"] = user
            self.session["idp"] = idp
            ensure_session_id(self.session)
            oauth_scope = self.get_oauth_client(idp).client_kwargs["scope"]
            if "offline_access" in oauth_scope:
                self.session["refresh_token"] = token.get("refresh_token")
            if self.log_signins:
                logging.info("User %s is logging in.", user.get("email"))

        return self.backend.redirect(get_url_base(self.app) or "/")

    def is_authorized(self):  # pylint: disable=C0116
        """Check whether the user is authenticated.

        Returns:
            True if the path is an OIDC route or a user is in the session.
        """
        map_adapter = Map(
            [
                Rule(x)
                for x in [
                    self.login_route,
                    self.logout_route,
                    self.callback_route,
                    self.idp_selection_route,
                ]
                if x
            ]
        ).bind("")
        if map_adapter.test(self.backend.current_path()):
            return True
        if "user" not in self.session:
            return False
        # Sessions from before revocable ids (or from an after_logged_in
        # override that skips super()) get one here, so logout can revoke them.
        ensure_session_id(self.session)
        return True


def get_oauth(app: dash.Dash | None = None) -> "OAuth | QuartOAuth":
    """Retrieve the OAuth object.

    :param app: dash.Dash
        Dash app or None, if None the current app is used
        calling `dash.get_app()`

    Returns:
        The Flask or Quart OAuth integration registered on the app server.

    Raises:
        RuntimeError: if no OAuth object has been registered yet.
    """
    if app is None:
        app = dash.get_app()

    # Retrieval is symmetric with storage: each backend knows where its own
    # make_oauth stashed the registry (extensions vs server.state), so there's
    # no need to probe every framework's location here.
    oauth = detect_backend(app.server).get_oauth(app.server)
    if oauth is not None:
        return oauth

    raise RuntimeError(
        "OAuth object is not yet defined. `OIDCAuth(app, **kwargs)` needs "
        "to be run before `get_oauth` is called."
    )

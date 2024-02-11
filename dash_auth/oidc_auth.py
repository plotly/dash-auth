import logging
import os
import re
from typing import Optional, Union, TYPE_CHECKING

import dash
from authlib.integrations.base_client import OAuthError
from authlib.integrations.flask_client import OAuth
from dash_auth.auth import Auth
from flask import redirect, request, session, url_for
from werkzeug.routing import Map, Rule

if TYPE_CHECKING:
    from authlib.integrations.flask_client.apps import (
        FlaskOAuth1App, FlaskOAuth2App
    )


class OIDCAuth(Auth):
    """Implements auth via OpenID."""

    def __init__(
        self,
        app: dash.Dash,
        secret_key: str = Optional[None],
        force_https_callback: Optional[Union[bool, str]] = None,
        client_kwargs: Optional[dict] = None,
        login_route: str = "/oidc/<idp>/login",
        logout_route: str = "/oidc/logout",
        callback_route: str = "/oidc/<idp>/callback",
        idp_selection_route: str = None,
        log_signins: bool = False,
        public_routes: Optional[list] = None,
        idp_name: str = "oidc",
        logout_page: str = None,
        **kwargs,
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
        client_kwargs : dict, optional
            Keyword arguments passed to the OAuth client
        login_route : str, optional
            The route for the login function, it requires a <idp>
            placeholder, by default "/oidc/<idp>/login".
        logout_route : str, optional
            The route for the logout function, by default "/oidc/logout".
        callback_route : str, optional
            The route for the OIDC redirect URI, it requires a <idp>
            placeholder, by default "/oidc/<idp>/callback".
        idp_selection_route : str, optional
            The route for the IDP selection function, by default None
        log_signins : bool, optional
            Whether to log signins, by default False
        **kwargs
            Additional keyword arguments are passed to oauth.register.

        Raises
        ------
        Exception
            Raise an exception if the app.server.secret_key is not defined
        """
        super().__init__(app, public_routes=public_routes)
        if force_https_callback is not None:
            self.force_https_callback = (
                os.getenv(force_https_callback) is not None
                if isinstance(force_https_callback, str)
                else force_https_callback
            )
        else:
            self.force_https_callback = False

        self.login_route = login_route
        self.logout_route = logout_route
        self.callback_route = callback_route
        self.log_signins = log_signins
        self.idp_selection_route = idp_selection_route
        self.logout_page = logout_page

        if secret_key is not None:
            app.server.secret_key = secret_key

        if app.server.secret_key is None:
            raise RuntimeError(
                """
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
                """
            )

        super().__init__(app)

        self.oauth = OAuth(app.server)
        self.register_provider(
            idp_name or "oidc",
            client_kwargs=client_kwargs,
            **kwargs
        )

        # Check that the login and callback rules have an <idp> placeholder
        if not re.findall(r"/<idp>(?=/|$)", login_route):
            raise Exception(
                "The login route must contain a <idp> placeholder."
            )
        if not re.findall(r"/<idp>(?=/|$)", callback_route):
            raise Exception(
                "The callback route must contain a <idp> placeholder."
            )

        app.server.add_url_rule(
            login_route,
            endpoint="oidc_login",
            view_func=self.login_request,
            methods=["GET"],
        )
        app.server.add_url_rule(
            logout_route,
            endpoint="oidc_logout",
            view_func=self.logout,
            methods=["GET"],
        )
        app.server.add_url_rule(
            callback_route,
            endpoint="oidc_callback",
            view_func=self.callback,
            methods=["GET"],
        )

    def register_provider(
        self,
        idp_name: str,
        *,
        client_kwargs: dict = None,
        **kwargs,
    ):
        client_kwargs = client_kwargs or {}
        client_kwargs.setdefault("scope", "openid email")
        self.oauth.register(
            idp_name, client_kwargs=client_kwargs, **kwargs
        )

    def get_oauth_client(self, idp: str):
        """Get the OAuth client."""
        if not idp:
            raise ValueError("`idp` should be set")

        client: Union[FlaskOAuth1App, FlaskOAuth2App] = (
            self.oauth.create_client(idp)
        )
        return client

    def get_oauth_kwargs(self, idp: str = None):
        """Get the OAuth kwargs."""
        if not idp:
            raise ValueError("`idp` should be set")

        kwargs: dict = (
            self.oauth._registry[idp][1]
        )
        return kwargs

    def login_request(self, idp: str = None):
        """Login the user."""
        if idp is None:
            if len(self.oauth._clients) == 1:
                idp = next(iter(self.oauth._clients))
            elif self.idp_selection_route:
                return redirect(self.idp_selection_route)
            else:
                return (
                    "Several OAuth providers are registered. "
                    "Please choose one.",
                    400,
                )

        kwargs = {"_external": True}
        if self.force_https_callback:
            kwargs["_scheme"] = "https"
        redirect_uri = url_for("oidc_callback", idp=idp, **kwargs)
        if request.headers.get("X-Forwarded-Host"):
            host = request.headers.get("X-Forwarded-Host")
            redirect_uri = redirect_uri.replace(request.host, host)

        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        return oauth_client.authorize_redirect(
            redirect_uri,
            **oauth_kwargs.get("authorize_redirect_kwargs", {}),
        )

    def logout(self):  # pylint: disable=C0116
        """Logout the user."""
        session.clear()
        base_url = self.app.config.get("url_base_pathname") or "/"
        page = self.logout_page or f"""
        <div style="display: flex; flex-direction: column;
        gap: 0.75rem; padding: 3rem 5rem;">
            <div>Logged out successfully</div>
            <div><a href="{base_url}">Go back</a></div>
        </div>
        """
        return page, 200

    def callback(self, idp: str = None):  # pylint: disable=C0116
        """Do the OIDC dance."""
        if idp is None:
            if len(self.oauth._clients) == 1:
                idp = next(iter(self.oauth._clients))
            else:
                return (
                    "Several OAuth providers are registered. "
                    "Please choose one.",
                    400,
                )

        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        try:
            token = oauth_client.authorize_access_token(
                **oauth_kwargs.get("authorize_token_kwargs", {}),
            )
        except OAuthError as err:
            return str(err), 401
        user = token.get("userinfo")
        if user:
            session["user"] = user
            if "offline_access" in oauth_client.client_kwargs["scope"]:
                session["refresh_token"] = token.get("refresh_token")
            if self.log_signins:
                logging.info("User %s is logging in.", user.get("email"))

        return redirect(self.app.config.get("url_base_pathname") or "/")

    def is_authorized(self):  # pylint: disable=C0116
        """Check whether ther user is authenticated."""

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
        return map_adapter.test(request.path) or "user" in session


def get_oauth(app: dash.Dash = None) -> OAuth:
    """Retrieve the OAuth object.

    :param app: dash.Dash
        Dash app or None, if None the current app is used
        calling `dash.get_app()`
    """
    if app is None:
        app = dash.get_app()

    oauth = getattr(app, "extensions", {}).get(
        "authlib.integrations.flask_client"
    )
    if oauth is not None:
        return oauth

    raise RuntimeError(
        "OAuth object is not yet defined. `OIDCAuth(app, **kwargs)` needs "
        "to be run before `get_oauth` is called."
    )

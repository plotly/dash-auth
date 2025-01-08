import logging
import os
import re
from typing import Optional, Union, TYPE_CHECKING

import dash
from authlib.integrations.base_client import OAuthError
from authlib.integrations.flask_client import OAuth
from dash_auth.auth import Auth
from flask import Response, redirect, request, session, url_for
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
        login_route: str = "/oidc/<idp>/login",
        logout_route: str = "/oidc/logout",
        callback_route: str = "/oidc/<idp>/callback",
        idp_selection_route: str = None,
        log_signins: bool = False,
        public_routes: Optional[list] = None,
        logout_page: Union[str, Response] = None,
        secure_session: bool = False,
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
            Whether to ensure the session is secure, setting the flasck config
            SESSION_COOKIE_SECURE and SESSION_COOKIE_HTTPONLY to True,
            by default False

        Raises
        ------
        Exception
            Raise an exception if the app.server.secret_key is not defined
        """
        super().__init__(app, public_routes=public_routes)

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

        if secure_session:
            app.server.config["SESSION_COOKIE_SECURE"] = True
            app.server.config["SESSION_COOKIE_HTTPONLY"] = True

        self.oauth = OAuth(app.server)

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
        """
        if not re.match(r"^[\w\-\. ]+$", idp_name):
            raise ValueError(
                "`idp_name` should only contain letters, numbers, hyphens, "
                "underscores, periods and spaces"
            )
        client_kwargs = kwargs.pop("client_kwargs", {})
        client_kwargs.setdefault("scope", "openid email")
        self.oauth.register(
            idp_name, client_kwargs=client_kwargs, **kwargs
        )

    def get_oauth_client(self, idp: str):
        """Get the OAuth client."""
        if idp not in self.oauth._registry:
            raise ValueError(f"'{idp}' is not a valid registered idp")

        client: Union[FlaskOAuth1App, FlaskOAuth2App] = (
            self.oauth.create_client(idp)
        )
        return client

    def get_oauth_kwargs(self, idp: str):
        """Get the OAuth kwargs."""
        if idp not in self.oauth._registry:
            raise ValueError(f"'{idp}' is not a valid registered idp")

        kwargs: dict = (
            self.oauth._registry[idp][1]
        )
        return kwargs

    def _create_redirect_uri(self, idp: str):
        """Create the redirect uri based on callback endpoint and idp."""
        kwargs = {"_external": True}
        if self.force_https_callback:
            kwargs["_scheme"] = "https"
        redirect_uri = url_for("oidc_callback", idp=idp, **kwargs)
        if request.headers.get("X-Forwarded-Host"):
            host = request.headers.get("X-Forwarded-Host")
            redirect_uri = redirect_uri.replace(request.host, host, 1)
        return redirect_uri

    def login_request(self, idp: str = None):
        """Start the login process."""

        # `idp` can be none here as login_request is called
        # without arguments in the before_request hook
        if idp not in self.oauth._registry:
            # If only one provider is registered, we don't need to
            # ask the user to pick one, just use the one
            if len(self.oauth._registry) == 1:
                idp = next(iter(self.oauth._clients))
            # If there are several providers and a `idp_selection_route`
            # was provided, redirect to it.
            elif self.idp_selection_route:
                return redirect(self.idp_selection_route)
            else:
                return (
                    "Several OAuth providers are registered. "
                    "Please choose one.",
                    400,
                )

        redirect_uri = self._create_redirect_uri(idp)
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
        return page

    def callback(self, idp: str):  # pylint: disable=C0116
        """Handle the OIDC dance and post-login actions."""
        if idp not in self.oauth._registry:
            return f"'{idp}' is not a valid registered idp", 400

        oauth_client = self.get_oauth_client(idp)
        oauth_kwargs = self.get_oauth_kwargs(idp)
        try:
            token = oauth_client.authorize_access_token(
                **oauth_kwargs.get("authorize_token_kwargs", {}),
            )
        except OAuthError as err:
            return str(err), 401

        user = token.get("userinfo")
        return self.after_logged_in(user, idp, token)

    def after_logged_in(self, user: Optional[dict], idp: str,  token: dict):
        """
        Post-login actions after successful OIDC authentication.
        For example, allows to pass custom attributes to the user session:
        class MyOIDCAuth(OIDCAuth):
            def after_logged_in(self, user, idp, token):
                if user:
                    user["params"] = value1
                return super().after_logged_in(user, idp, token)
        """
        if user:
            session["user"] = user
            session["idp"] = idp
            oauth_scope = self.get_oauth_client(idp).client_kwargs["scope"]
            if "offline_access" in oauth_scope:
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

    oauth = getattr(app.server, "extensions", {}).get(
        "authlib.integrations.flask_client"
    )
    if oauth is not None:
        return oauth

    raise RuntimeError(
        "OAuth object is not yet defined. `OIDCAuth(app, **kwargs)` needs "
        "to be run before `get_oauth` is called."
    )

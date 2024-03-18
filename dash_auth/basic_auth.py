import base64
import logging
from typing import Dict, List, Optional, Union, Callable
import flask
from dash import Dash

from .auth import Auth

UserGroups = Dict[str, List[str]]


class BasicAuth(Auth):
    def __init__(
        self,
        app: Dash,
        username_password_list: Union[list, dict] = None,
        auth_func: Callable = None,
        public_routes: Optional[list] = None,
        user_groups: Optional[
            Union[UserGroups, Callable[[str], UserGroups]]
        ] = None,
        secret_key: str = None
    ):
        """Add basic authentication to Dash.

        :param app: Dash app
        :param username_password_list: username:password list, either as a
            list of tuples or a dict
        :param auth_func: python function accepting two string
            arguments (username, password) and returning a
            boolean (True if the user has access otherwise False).
        :param public_routes: list of public routes, routes should follow the
            Flask route syntax
        :param user_groups: a dict or a function returning a dict
            Optional group for each user, allowing to protect routes and
            callbacks depending on user groups
        :param secret_key: Flask secret key
            A string to protect the Flask session, by default None.
            It is required if you need to store the current user
            in the session.
            Generate a secret key in your Python session
            with the following commands:
            >>> import os
            >>> import base64
            >>> base64.b64encode(os.urandom(30)).decode('utf-8')
            Note that you should not do this dynamically:
            you should create a key and then assign the value of
            that key in your code.
        """
        super().__init__(app, public_routes=public_routes)
        self._auth_func = auth_func
        self._user_groups = user_groups
        if secret_key is not None:
            app.server.secret_key = secret_key

        if self._auth_func is not None:
            if username_password_list is not None:
                raise ValueError(
                    "BasicAuth can only use authorization function "
                    "(auth_func kwarg) or username_password_list, "
                    "it cannot use both."
                )
        else:
            if username_password_list is None:
                raise ValueError(
                    "BasicAuth requires username/password map "
                    "or user-defined authorization function."
                )
            else:
                self._users = (
                    username_password_list
                    if isinstance(username_password_list, dict)
                    else {k: v for k, v in username_password_list}
                )

    def is_authorized(self):
        header = flask.request.headers.get('Authorization', None)
        if not header:
            return False
        username_password = base64.b64decode(header.split('Basic ')[1])
        username_password_utf8 = username_password.decode('utf-8')
        username, password = username_password_utf8.split(':', 1)
        authorized = False
        if self._auth_func is not None:
            try:
                authorized = self._auth_func(username, password)
            except Exception:
                logging.exception("Error in authorization function.")
                return False
        else:
            authorized = self._users.get(username) == password
        if authorized:
            try:
                flask.session["user"] = {"email": username, "groups": []}
                if callable(self._user_groups):
                    flask.session["user"]["groups"] = self._user_groups(
                        username
                    )
                elif self._user_groups:
                    flask.session["user"]["groups"] = self._user_groups.get(
                        username, []
                    )
            except RuntimeError:
                logging.warning(
                    "Session is not available. Have you set a secret key?"
                )
        return authorized

    def login_request(self):
        return flask.Response(
            'Login Required',
            headers={'WWW-Authenticate': 'Basic realm="User Visible Realm"'},
            status=401
        )

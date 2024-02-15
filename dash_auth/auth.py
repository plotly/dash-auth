from __future__ import absolute_import
from abc import ABC, abstractmethod
from typing import Optional

from dash import Dash
from flask import request

from .public_routes import (
    add_public_routes, get_public_callbacks, get_public_routes
)


class Auth(ABC):
    def __init__(
        self,
        app: Dash,
        public_routes: Optional[list] = None,
        **obsolete
    ):
        """Auth base class for authentication in Dash.

        :param app: Dash app
        :param public_routes: list of public routes, routes should follow the
            Flask route syntax
        """

        # Deprecated arguments
        if obsolete:
            raise TypeError(
                f"Auth got unexpected keyword arguments: {list(obsolete)}"
            )

        self.app = app
        self._protect()
        if public_routes is not None:
            add_public_routes(app, public_routes)

    def _protect(self):
        """Add a before_request authentication check on all routes.

        The authentication check will pass if either
            * The endpoint is marked as public via `add_public_routes`
            * The request is authorised by `Auth.is_authorised`
        """

        server = self.app.server

        @server.before_request
        def before_request_auth():

            public_routes = get_public_routes(self.app)
            public_callbacks = get_public_callbacks(self.app)
            # Handle Dash's callback route:
            # * Check whether the callback is marked as public
            # * Check whether the callback is performed on route change in
            #   which case the path should be checked against the public routes
            if request.path == "/_dash-update-component":
                body = request.get_json()

                # Check whether the callback is marked as public
                if body["output"] in public_callbacks:
                    return None

                # Check whether the callback has an input using the pathname,
                # such a callback will be a routing callback and the pathname
                # should be checked against the public routes
                pathname = next(
                    (
                        inp.get("value") for inp in body["inputs"]
                        if isinstance(inp, dict)
                        and inp.get("property") == "pathname"
                    ),
                    None,
                )
                if pathname and public_routes.test(pathname):
                    return None

            # If the route is not a callback route, check whether the path
            # matches a public route, or whether the request is authorised
            if public_routes.test(request.path) or self.is_authorized():
                return None

            # Otherwise, ask the user to log in
            return self.login_request()

    def is_authorized_hook(self, func):
        self._auth_hooks.append(func)
        return func

    @abstractmethod
    def is_authorized(self):
        pass

    @abstractmethod
    def auth_wrapper(self, f):
        pass

    @abstractmethod
    def index_auth_wrapper(self, f):
        pass

    @abstractmethod
    def login_request(self):
        pass

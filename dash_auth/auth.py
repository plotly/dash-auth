from __future__ import absolute_import
from abc import ABC, abstractmethod
from typing import Optional, Union

from dash import Dash
from flask import request

from .public_routes import (
    add_public_routes, get_public_callbacks, get_public_routes
)
from .group_protection import protect_layouts


class Auth(ABC):
    def __init__(
        self,
        app: Dash,
        public_routes: Optional[list] = None,
        auth_protect_layouts: Optional[Union[dict, bool]] = False,
        auth_protect_layouts_kwargs: Optional[dict] = None,
        page_container: Optional[str] = None,
        **obsolete
    ):
        """Auth base class for authentication in Dash.

        :param app: Dash app
        :param public_routes: list of public routes, routes should follow the
            Flask route syntax
        :param auth_protect_layouts: bool, defaults to False.
            If true, runs protect_layout()
        :param auth_protect_layouts_kwargs: dict, if provided is passed to the
            protect_layout as kwargs
        :param page_container: string, id of the page container in the app.
            If not provided, this will set the page_container_test to True,
            meaning all pathname callbacks will be judged.
        """

        # Deprecated arguments
        if obsolete:
            raise TypeError(
                f"Auth got unexpected keyword arguments: {list(obsolete)}"
            )

        self.app = app
        self._protect()
        self.auth_protect_layouts = auth_protect_layouts
        self.page_container = page_container
        if public_routes is not None:
            add_public_routes(app, public_routes)
        if self.auth_protect_layouts:
            protect_layouts(public_routes=get_public_routes(self.app), **(auth_protect_layouts_kwargs or {}))

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

                pathname = next(
                    (
                        inp.get("value") for inp in body["inputs"]
                        if isinstance(inp, dict)
                           and inp.get("property") == "pathname"
                    ),
                    None,
                )
                if self.page_container:
                    page_container_test = next(
                        (
                            out for out in body["outputs"]
                            if isinstance(out, dict)
                               and out.get('id') == self.page_container
                               and out.get("property") == "children"
                        ),
                        None,
                    )
                else:
                    page_container_test = True

                # Check whether the callback has an input using the pathname,
                # such a callback will be a routing callback and the pathname
                # should be checked against the public routes
                if not self.auth_protect_layouts:
                    if pathname and page_container_test and public_routes.test(pathname):
                        return None
                else:
                    # protected by layout
                    if pathname and page_container_test:
                        return None

            # If the route is not a callback route, check whether the path
            # matches a public route, or whether the request is authorised
            if public_routes.test(request.path) or self.is_authorized():
                return None

            # Otherwise, ask the user to log in
            return self.login_request()

    @abstractmethod
    def is_authorized(self):
        pass

    @abstractmethod
    def login_request(self):
        pass

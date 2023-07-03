from __future__ import absolute_import
from abc import ABC, abstractmethod

from dash import Dash
from flask import Flask, request
from werkzeug.datastructures import ImmutableDict
from werkzeug.routing import Map, MapAdapter, Rule

# Add PUBLIC_ROUTES in the default Flask config
default_config = Flask.default_config
Flask.default_config = ImmutableDict(
    **default_config, **{"PUBLIC_ROUTES": Map([]).bind("")}
)


class Auth(ABC):
    def __init__(self, app: Dash, **_kwargs):
        self.app = app
        self._protect()

    def _protect(self):
        """Add a before_request authentication check on all routes.

        The authentication check will pass if either
            * The endpoint is marked as public via `add_public_routes`
            * The request is authorised by `Auth.is_authorised`
        """

        server = self.app.server

        @server.before_request
        def before_request_auth():
            # Check whether the path matches a public route,
            # or whether the request is authorised
            if (
                server.config["PUBLIC_ROUTES"].test(request.path)
                or self.is_authorized()
            ):
                return None

            # Ask the user to log in
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


def add_public_routes(app: Dash, routes: list):
    """Add routes to the public routes list.

    The routes passed should follow the Flask route syntax.
    e.g. "/login", "/user/<user_id>/public"
    """
    public_routes: MapAdapter = app.server.config["PUBLIC_ROUTES"]
    for route in routes:
        public_routes.map.add(Rule(route))

from __future__ import absolute_import
from abc import ABC, abstractmethod

from dash import Dash
from flask import request
from werkzeug.routing import Map, Rule


class Auth(ABC):
    def __init__(self, app: Dash, **_kwargs):
        self.app = app
        self._protect()

    def _protect(self):
        """Add a before_request authentication check on all routes.

        The authentication check will pass if either
            * The endpoint is marked as public via
              `app.server.config["PUBLIC_ROUTES"]`
              (PUBLIC_ROUTES should follow the Flask route syntax)
            * The request is authorised by `Auth.is_authorised`
        """

        server = self.app.server

        @server.before_request
        def before_request_auth():
            public_paths_map = Map(
                [Rule(p) for p in server.config.get("PUBLIC_ROUTES", [])]
            )
            public_paths_map_adapter = public_paths_map.bind("tmp")
            if not (
                public_paths_map_adapter.test(request.path)
                or self.is_authorized()
            ):
                return self.login_request()
            return None

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

from __future__ import absolute_import
from abc import ABC, abstractmethod

from dash import Dash
from flask import request


class Auth(ABC):
    def __init__(self, app: Dash, **_kwargs):
        self.app = app
        self._protect()

    def _protect(self):
        """Add a before_request authentication check on all routes.

        The authentication check will pass if either
            * The endpoint is marked as public via
              `app.server.config["PUBLIC_ENDPOINTS"]`
            * The request is authorised by `Auth.is_authorised`
        """

        server = self.app.server

        @server.before_request
        def before_request_auth():
            if not (
                request.endpoint in server.config.get("PUBLIC_ENDPOINTS", [])
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

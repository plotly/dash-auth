from __future__ import absolute_import
from abc import ABC, abstractmethod

from dash import Dash


class Auth(ABC):
    def __init__(self, app: Dash, **obsolete):
        """Auth base class for authentication in Dash.

        :param app: Dash app
        """

        # Deprecated arguments
        if obsolete:
            raise TypeError(
                f"Auth got unexpected keyword arguments: {list(obsolete)}"
            )

        self.app = app
        self._protect()

    def _protect(self):
        """Add a before_request authentication check on all routes.

        The authentication check will pass if the request
        is authorised by `Auth.is_authorised`
        """

        server = self.app.server

        @server.before_request
        def before_request_auth():

            # Check whether the request is authorised
            if self.is_authorized():
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

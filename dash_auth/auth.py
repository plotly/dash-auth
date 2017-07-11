from abc import ABCMeta, abstractmethod
import flask
from six import iteritems


class Auth(object):
    __metaclass__ = ABCMeta

    def __init__(self, app):
        self.app = app
        self._overwrite_index()
        self._protect_views()

    def _overwrite_index(self):
        original_index = self.app.server.view_functions['index']

        def wrap_index(*args, **kwargs):
            if self.is_authorized():
                return original_index(*args, **kwargs)
            else:
                return self.login_html()

        self.app.server.view_functions['index'] = wrap_index

    def _protect_views(self):
        # TODO - Maybe just whitelist
        protected_views = [
            'dependencies',
            'dispatch',
            'serve_component_suites',
            'serve_layout',
            'serve_routes'
        ]
        for view in protected_views:
            original_view = self.app.server.view_functions[view]
            self.app.server.view_functions[view] = \
                self.auth_wrapper(original_view)

    @abstractmethod
    def is_authorized(self):
        pass

    @abstractmethod
    def auth_wrapper(self):
        pass

    @abstractmethod
    def login_html(self):
        pass

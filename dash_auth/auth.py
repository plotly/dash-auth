
from __future__ import absolute_import
from abc import ABCMeta, abstractmethod
import flask
from six import iteritems, add_metaclass


@add_metaclass(ABCMeta)
class Auth(object):
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
                return self.login_request()

        self.app.server.view_functions['index'] = wrap_index

    def _protect_views(self):
        # TODO - allow users to white list in case they add their own views
        for view_name, view_method in iteritems(self.app.server.view_functions):
            if view_name != 'index':
                self.app.server.view_functions[view_name] = \
                    self.auth_wrapper(view_method)

    @abstractmethod
    def is_authorized(self):
        pass

    @abstractmethod
    def auth_wrapper(self, f):
        pass

    @abstractmethod
    def login_request(self):
        pass

from __future__ import absolute_import
from abc import ABCMeta, abstractmethod
from six import iteritems, add_metaclass


@add_metaclass(ABCMeta)
class Auth(object):
    def __init__(self, app):
        self.app = app
        self._index_view_name = app.config['routes_pathname_prefix']
        self._overwrite_index()
        self._protect_views()
        self._index_view_name = app.config['routes_pathname_prefix']

    def _overwrite_index(self):
        original_index = self.app.server.view_functions[self._index_view_name]

        def wrap_index(*args, **kwargs):
            response = self.auth_wrapper(original_index)(*args, **kwargs)
            if response.status_code == 403:
                return self.login_request()
            else:
                return response

        self.app.server.view_functions[self._index_view_name] = wrap_index

    def _protect_views(self):
        # TODO - allow users to white list in case they add their own views
        for view_name, view_method in iteritems(
                self.app.server.view_functions):
            if view_name != self._index_view_name:
                self.app.server.view_functions[view_name] = \
                    self.auth_wrapper(view_method)

    @abstractmethod
    def auth_wrapper(self, f):
        pass

    @abstractmethod
    def login_request(self):
        pass

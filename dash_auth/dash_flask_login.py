from dash import Dash
from flask import Flask
try:
    from flask_login import login_required
except ImportError:
    print('Please install flask_login to proceed')


class DashFlaskLogin(Dash):
    def __init__(
        self,
        name=None,
        server=None,
        static_folder=None,
        url_base_pathname='/',
        authentication_required=False,
        **kwargs
    ):
        super(DashFlaskLogin, self).__init__(
        name=name,
        static_folder=static_folder,
        url_base_pathname=url_base_pathname,
        **kwargs
    )
        # allow users to supply their own flask server
        if server is not None:
            self.server = server
        else:
            if name is None:
                name = 'dash'
            self.server = Flask(name, static_folder=static_folder)

        def add_url(name, view_func, methods=['GET']):
            self.server.add_url_rule(
                name,
                view_func=view_func,
                endpoint=name,
                methods=methods
            )

        add_url(
            '{}_dash-layout'.format(self.config['routes_pathname_prefix']),
            self.serve_layout if not authentication_required else login_required(self.serve_layout))

        add_url(
            '{}_dash-dependencies'.format(
                self.config['routes_pathname_prefix']),
            self.dependencies if not authentication_required else login_required(self.dependencies))

        add_url(
            '{}_dash-update-component'.format(
                self.config['routes_pathname_prefix']
            ),
            self.dispatch if not authentication_required else login_required(self.dispatch),
            ['POST'])

        add_url((
            '{}_dash-component-suites'
            '/<string:package_name>'
            '/<path:path_in_package_dist>').format(
                self.config['routes_pathname_prefix']
            ),
            self.serve_component_suites if not authentication_required else login_required(self.serve_component_suites))

        add_url(
            '{}_dash-routes'.format(self.config['routes_pathname_prefix']),
            self.serve_routes if not authentication_required else login_required(self.serve_routes))

        add_url(
            self.config['routes_pathname_prefix'],
            self.index if not authentication_required else login_required(self.index))

        # catch-all for front-end routes
        add_url(
            '{}<path:path>'.format(self.config['routes_pathname_prefix']),
            self.index if not authentication_required else login_required(self.index))

        self.server.before_first_request(self._setup_server)

        self._layout = None
        self._cached_layout = None
        self.routes = []
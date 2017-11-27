from dash import Dash
from flask import Flask
try:
    from flask_login import login_required, LoginManager
except ImportError:
    print('Please run "pip install flask_login" to proceed')


class FlaskLoginAuth():
    def __init__(self, app):
        """
        app: A Dash object to be login-protected
        """
        self.initial_app = app
        self.apps_list = [app]

        # Protect all views
        self.__protect_views()
        
    def add_app(self, app):
        """
        Add an app to the server to protected by a login requirement.  All apps must
        share the same Flask server.

            app: A Dash object to be login-protected
        """
        if not app.server is self.initial_app.server:
            raise Exception('Each Dash app must share the same Flask server')
        self.apps_list.append(app)
        self.__protect_views()
        
    def __protect_views(self):
        """
        Alter the view functions of the server to require login.
        """
        for app in self.apps_list:
            for view_func in app.server.view_functions.keys():
                if view_func.startswith(app.config['routes_pathname_prefix']):
                    app.server.view_functions[view_func] = login_required(app.server.view_functions[view_func])
        
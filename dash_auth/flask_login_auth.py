from dash import Dash
from flask import Flask
try:
    from flask_login import login_required
except ImportError:
    print('Please run "pip install flask_login" to proceed')


class FlaskLoginAuth():
    def __init__(self, app):
        self.app = app

        for view_func in self.app.server.view_functions.keys():
            if view_func.startswith(self.app.config['routes_pathname_prefix']):
                self.app.server.view_functions[view_func] = login_required(self.app.server.view_functions[view_func])
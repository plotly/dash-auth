import os
import jinja2
import hashlib
from dash import Dash
from flask import Flask, request, render_template, flash, abort, session, redirect
try:
    from flask_login import login_required, LoginManager, UserMixin, login_user, logout_user, current_user
except ImportError:
    print('Please run "pip install flask_login" to proceed')

TEMPLATE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')

class FlaskLoginAuth():
    def __init__(self, app, use_default_views=False, users=None):
        """
        app: A Dash object to be login-protected
        use_default_views: If set to True, default views will be set for login, logout, and user management
        users: Should be one of -
                A) A valid SQLAlchemy or SQLite connection string
                B) A list of tuples of the format (USER_ID, USER_NAME) which will be used to create a set of DefaultUser objects
                C) A list of valide Flask-Login User objects
                D) None - in which case the application will have only one user with USER_NAME = admin and PASSWORD = admin
        """
        self.initial_app = app
        self.apps_list = [app]

        # Protect all views
        self.__protect_views()

        if use_default_views:
            # Setup the LoginManager for the server
            self.login_manager = LoginManager()
            self.login_manager.init_app(self.initial_app.server)
            self.login_manager.login_view = "/login"

            # callback to reload the user object
            @self.login_manager.user_loader
            def load_user(userid):
                return DefaultUser(userid)

            # Add a FileSystemLoader for the default templates
            default_loader = jinja2.ChoiceLoader([
                self.initial_app.server.jinja_loader,
                jinja2.FileSystemLoader([TEMPLATE_FOLDER])
            ])

            self.initial_app.server.jinja_loader = default_loader
            self.serve_default_views()

        else:pass

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

    def serve_default_views(self):

        self.initial_app.server.add_url_rule(
            '/login',
            view_func=self.__default_login_view,
            methods=['GET', 'POST']
        )

        self.initial_app.server.add_url_rule(
            '/logout',
            view_func=self.__default_logout_view,
            methods=['GET', 'POST']
        )

    def __default_login_view(self):
        if request.method == 'POST':
            username = request.form['username'].lower()
            password = request.form['password']
            password = hash_str(password)

            user = DefaultUser(username)
            if user.name:
                if password == hash_str('password'):

                    login_user(user)
                    session['username'] = user.name
                    return redirect('/app1')
                else:
                    flash('Login Failed!  Please try again.')
                    return abort(401)
            else:
                flash('Login Failed!  Please try again.')
                return abort(401)
        else:
            return render_template('default_login.html')

    @login_required
    def __default_logout_view(self):
        logout_user()
        flash('You have logged out!')
        return render_template('default_logout.html')

class DefaultUser(UserMixin):

    def __init__(self, id):
        self.id = id
        self.name = "user" + str(id)
        self.password = hash_str(self.name + "_secret")

    def __repr__(self):
        return "%d/%s/%s" % (self.id, self.name, self.password)


def hash_str(string):
    hasher = hashlib.md5()
    hasher.update(string.encode('utf-8'))
    hashed = hasher.hexdigest()
    return hashed

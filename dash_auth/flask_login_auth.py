import os
import jinja2
import hashlib
import sqlite3
import warnings
from dash import Dash
from flask import Flask, request, render_template, flash, abort, session, redirect
try:
    from flask_login import login_required, LoginManager, UserMixin, login_user, logout_user, current_user
except ImportError:
    print('Please run "pip install flask_login" to proceed')
try:
    import sqlalchemy
except ImportError:
    print('Please run "pip install sqlite3"')

TEMPLATE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')

class FlaskLoginAuth():
    def __init__(self, app, use_default_views=False, users=None):
        """
        app: A Dash object to be login-protected
        use_default_views: If set to True, default views will be set for login, logout, and user management
        users: Should be one of -
                A) A valid SQLAlchemy connection string or SQLAlchemy/sqlite compatible Connection object for a database containing a USERS table
                   with a list of application users.
                B) A list of tuples of the format (<USER_NAME>, <PASSWORD>) where each element is a unicode string. This will be used to create a list of DefaultUser objects.
                C) A list of objects which subclass flask_login.UserMixin
                D) None - in which case the application will have only one user with USER_NAME = 'admin' and PASSWORD = 'admin'.
        """
        self.initial_app = app
        self.server = self.initial_app.server
        self.apps_list = [app]

        # Protect all views
        self.__protect_views()

        if use_default_views:
            # Setup the LoginManager for the server
            self.login_manager = LoginManager()
            self.login_manager.init_app(self.server)
            self.login_manager.login_view = "/login"

            # callback to reload the user object
            @self.login_manager.user_loader
            def load_user(userid):
                return self.users.get_user(userid)

            # Add a FileSystemLoader for the default templates
            default_loader = jinja2.ChoiceLoader([
                self.server.jinja_loader,
                jinja2.FileSystemLoader([TEMPLATE_FOLDER])
            ])

            self.server.jinja_loader = default_loader
            self.serve_default_views()

        else:pass

        # Check if users was provided, if not set a single admin user
        if not users:
            warnings.warn('''No connection string or list of users supplied, defaulting to single user environment with USER_NAME: admin and PASSWORD: admin.\nYou will be unable to change this password or add other users.''')
            self.users = UserMap([DefaultUser('admin', 'admin')])

        # Check if users is a list, if so, check if it's a list of string or list of User objects
        elif isinstance(users, list):
            # If all objects are strings, create a UserMap from the strings
            if all(isinstance(users[i], tuple) for i in range(len(users))):
                self.users = UserMap([DefaultUser(users[i][0], users[i][1]) for i in range(len(users))])

            # If all objects are a subclass of UserMixin, create a UserMap of the objects
            elif all(issubclass(type(users[i]), UserMixin) for i in range(len(users))):
                self.users = UserMap(users)

            else:
                raise TypeError("All objects in the list must be a tuple of form (USER_NAME, PASSWORD) or a subclass of flask_login.UserMixin")

        elif isinstance(users, str) or isinstance(users, sqlite3.Connection):
            pass
        else:
            raise TypeError('''
The "users" parameter provided in __init__ is not a valid type.
"users" must be one of %s, %s, %s, or %s.  Provided type was %s''' % (type('s'), type([]), sqlite3.Connection, type(None), type(users))
                    )


    def add_app(self, app):
        """
        Add an app to the server to protected by a login requirement.  All apps must
        share the same Flask server.

            app: A Dash object to be login-protected
        """
        if not app.server is self.server:
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

        self.server.add_url_rule(
            '/login',
            view_func=self.__default_login_view,
            methods=['GET', 'POST']
        )

        self.server.add_url_rule(
            '/logout',
            view_func=self.__default_logout_view,
            methods=['GET']
        )

    def __default_login_view(self):
        if request.method == 'POST':
            username = request.form['username'].lower()
            password = request.form['password']
            password = hash_str(password)

            user = self.users.get_user(username)

            if user:
                if password == user.password:
                    login_user(user)
                    return redirect('/app1')
                else:
                    flash('Login Failed!  Please try again.')
                    return render_template('default_login.html')
            else:
                flash('Login Failed!  Please try again.')
                return render_template('default_login.html')
        else:
            return render_template('default_login.html')

    @login_required
    def __default_logout_view(self):
        logout_user()
        flash('You have logged out!')
        return render_template('default_logout.html')

class DefaultUser(UserMixin):

    def __init__(self, name=None, password=None):
        self.id = name
        self.name = name
        if password:
            self.password = hash_str(password)
        else:
            self.password = hash_str('password')

    def __eq__(self, other):
        return self.id == other.id

class UserMap():

    def __init__(self, users):
        """
        users: a list of DefaultUser objects
        """
        self.users = users
        self.user_map = {}
        for i in range(len(self.users)):
            self.user_map.update({users[i].id:users[i]})

    def get_user(self, id):
        try:
            return self.user_map[id]
        except:
            return None


def hash_str(string):
    hasher = hashlib.md5()
    hasher.update(string.encode('utf-8'))
    hashed = hasher.hexdigest()
    return hashed

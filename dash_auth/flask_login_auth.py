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
    def __init__(self, app, use_default_views=False, users=None, auto_hash=True, hash_function=None):
        """
        app: A Dash object to be login-protected
        use_default_views: If set to True, default views will be set for login and logout
        users: Should be one of -
            #TODO: add SQLAlchemy compatibility
            A) A valid SQLAlchemy connection string or SQLAlchemy/sqlite compatible Connection object for a database containing a USERS table
               with a list of application users.  The USERS table must contain two string columns: USERNAME and PASSWORD
            B) A list of tuples of the format (<USERNAME>, <PASSWORD>) where each element is a unicode string. This will be used to create a list of DefaultUser objects.
            C) A list of objects which subclass flask_login.UserMixin, these objects must have an id and password.
            D) None - in which case the application will have only one user with USERNAME = 'admin' and PASSWORD = 'admin'.
        auto_hash: boolean - True if you would like FlaskLoginAuth to hash passwords for you, False otherwise.  If False, and your passwords
        have been hashed previously, you should provide the same hash function that was used to hash the passwords in the hash_function parameter.
        If your passwords are not hashed and auto_hash is set to false, you must pass None to the hash_function.
        hash_function: callable - A hashing function to be used in the login view.  If auto_hash = True, you can pass a custom hash function
        to be used in user creation and login.
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

            self.server.config.update(
                SECRET_KEY = os.urandom(12),
            )

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

            self.auto_hash = auto_hash

            # If they have elected to not have FlaskLoginAuth automatically hash passwords
            # set the hash_function to the function provided or to simply return x
            if not self.auto_hash:
                if hash_function:
                    self.hash_function = hash_function
                else:
                    def return_val(x):return x
                    self.hash_function = return_val

            else:
                if hash_function:
                    self.hash_function = hash_function
                else:
                    self.hash_function = hash_str

            # Check if users was provided, if not set a single admin user
            if not users:
                warnings.warn('''No connection string or list of users supplied, defaulting to single user environment with USER_NAME: admin and PASSWORD: admin.\nYou will be unable to change this password or add other users.''')
                self.users = UserMap([DefaultUser('admin', 'admin', True, self.hash_function)])

            # Check if users is a list, if so, check if it's a list of string or list of User objects
            elif isinstance(users, list):

                warnings.warn('''By simply supplying a list of authorized users, your users will be unable to change their passwords.''')
                # If all objects are strings, create a UserMap from the strings
                if all(isinstance(users[i], tuple) for i in range(len(users))):
                    self.users = UserMap([DefaultUser(users[i][0], users[i][1], self.auto_hash, self.hash_function) for i in range(len(users))])

                # If all objects are a subclass of UserMixin, create a UserMap of the objects
                elif all(issubclass(type(users[i]), UserMixin) for i in range(len(users))):
                    if self.auto_hash:
                        warnings.warn('''Supplying a list of UserMixin subclass objects does not allow automated password hashing.  Please ensure passwords are safely stored''')
                    self.users = UserMap(users)
                    if auto_hash:
                        for user in self.users.user_map.values():
                            user.password = self.hash_function(user.password)

                else:
                    raise TypeError("All objects in the list must be a tuple of form (USER_NAME, PASSWORD) or a subclass of flask_login.UserMixin")

            elif isinstance(users, str):
                pass

            elif isinstance(users, sqlite3.Connection):
                cursor = users.execute("SELECT * FROM USERS")
                result_set = cursor.fetchall()

                self.users = UserMap([DefaultUser(result_set[i][0], result_set[i][1], self.auto_hash, self.hash_function) for i in range(len(result_set))])

            else:
                raise TypeError('''
    The "users" parameter provided in __init__ is not a valid type.
    "users" must be one of %s, %s, %s, or %s.  Provided type was %s''' % (type('s'), type([]), sqlite3.Connection, type(None), type(users))
                        )

        else:pass

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
            password = self.hash_function(password)

            user = self.users.get_user(username)

            if user:
                if password == user.password:
                    login_user(user)
#TODO: make this more logical, maybe this should redirect to an index view?                    
                    return redirect(request.args.get('next') or '/login')
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

    def __init__(self, name, password=None, auto_hash=True, hash_function=None):
        self.id = name.lower()
        self.username = name.lower()
        if auto_hash:
            if password:
                self.password = hash_function(password)
            else:
                self.password = hash_function('password')
        else:
            if password:
                self.password = password
            else:
                self.password = 'password'

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

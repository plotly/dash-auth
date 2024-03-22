## Dash Authorization and Login

Docs: [https://dash.plotly.com/authentication](https://dash.plotly.com/authentication)

License: MIT

Tests: [![CircleCI](https://circleci.com/gh/plotly/dash-auth.svg?style=svg)](https://circleci.com/gh/plotly/dash-auth)

For local testing, create a virtualenv, install the dev requirements, and run individual
tests or test classes:

```
python -m venv venv
. venv/bin/activate
pip install -r dev-requirements.txt
python -k ba001
```

Note that Python 3.8 or greater is required.

## Usage

### Basic Authentication

To add basic authentication, add the following to your Dash app:

```python
from dash import Dash
from dash_auth import BasicAuth

app = Dash(__name__)
USER_PWD = {
    "username": "password",
    "user2": "useSomethingMoreSecurePlease",
}
BasicAuth(app, USER_PWD)
```

One can also use an authorization python function instead of a dictionary/list of usernames and passwords:

```python
from dash import Dash
from dash_auth import BasicAuth

def authorization_function(username, password):
    if (username == "hello") and (password == "world"):
        return True
    else:
        return False


app = Dash(__name__)
BasicAuth(app, auth_func = authorization_function)
```

### Public routes

You can whitelist routes from authentication with the `add_public_routes` utility function,
or by passing a `public_routes` argument to the Auth constructor.
The public routes should follow [Flask's route syntax](https://flask.palletsprojects.com/en/2.3.x/quickstart/#routing).

```python
from dash import Dash
from dash_auth import BasicAuth, add_public_routes

app = Dash(__name__)
USER_PWD = {
    "username": "password",
    "user2": "useSomethingMoreSecurePlease",
}
BasicAuth(app, USER_PWD, public_routes=["/"])

add_public_routes(app, public_routes=["/user/<user_id>/public"])
```

NOTE: If you are using server-side callbacks on your public routes, you should also use dash_auth's new `public_callback` rather than the default Dash callback.
Below is an example of a public route and callbacks on a multi-page Dash app using Dash's pages API:

*app.py*
```python
from dash import Dash, html, dcc, page_container
from dash_auth import BasicAuth

app = Dash(__name__, use_pages=True, suppress_callback_exceptions=True)
USER_PWD = {
    "username": "password",
    "user2": "useSomethingMoreSecurePlease",
}
BasicAuth(app, USER_PWD, public_routes=["/", "/user/<user_id>/public"])

app.layout = html.Div(
    [
        html.Div(
            [
                dcc.Link("Home", href="/"),
                dcc.Link("John Doe", href="/user/john_doe/public"),
            ],
            style={"display": "flex", "gap": "1rem", "background": "lightgray", "padding": "0.5rem 1rem"},
        ),
        page_container,
    ],
    style={"display": "flex", "flexDirection": "column"},
)

if __name__ == "__main__":
    app.run_server(debug=True)
```

---
*pages/home.py*
```python
from dash import Input, Output, html, register_page
from dash_auth import public_callback

register_page(__name__, "/")

layout = [
    html.H1("Home Page"),
    html.Button("Click me", id="home-button"),
    html.Div(id="home-contents"),
]

# Note the use of public callback here rather than the default Dash callback
@public_callback(
    Output("home-contents", "children"),
    Input("home-button", "n_clicks"),
)
def home(n_clicks):
    if not n_clicks:
        return "You haven't clicked the button."
    return "You clicked the button {} times".format(n_clicks)
```

---
*pages/public_user.py*
```python
from dash import html, dcc, register_page

register_page(__name__, path_template="/user/<user_id>/public")

def layout(user_id: str):
    return [
        html.H1(f"User {user_id} (public)"),
        dcc.Link("Authenticated user content", href=f"/user/{user_id}/private"),
    ]
```

---
*pages/private_user.py*
```python
from dash import html, register_page

register_page(__name__, path_template="/user/<user_id>/private")

def layout(user_id: str):
    return [
        html.H1(f"User {user_id} (authenticated only)"),
        html.Div("Members-only information"),
    ]
```

### OIDC Authentication

To add authentication with OpenID Connect, you will first need to set up an OpenID Connect provider (IDP).
This typically requires creating
* An application in your IDP
* Defining the redirect URI for your application, for testing locally you can use http://localhost:8050/oidc/callback
* A client ID and secret for the application

Once you have set up your IDP, you can add it to your Dash app as follows:

```python
from dash import Dash
from dash_auth import OIDCAuth

app = Dash(__name__)

auth = OIDCAuth(app, secret_key="aStaticSecretKey!")
auth.register_provider(
    "idp",
    token_endpoint_auth_method="client_secret_post",
    # Replace the below values with your own
    # NOTE: Do not hardcode your client secret!
    client_id="<my-client-id>",
    client_secret="<my-client-secret>",
    server_metadata_url="<my-idp-.well-known-configuration>",
)
```

Once this is done, connecting to your app will automatically redirect to the IDP login page.

#### Multiple OIDC Providers

For multiple OIDC providers, you can use `register_provider` to add new ones after the OIDCAuth has been instantiated.

```python
from dash import Dash, html
from dash_auth import OIDCAuth
from flask import request, redirect, url_for

app = Dash(__name__)

app.layout = html.Div([
    html.Div("Hello world!"),
    html.A("Logout", href="/oidc/logout"),
])

auth = OIDCAuth(
    app,
    secret_key="aStaticSecretKey!",
    # Set the route at which the user will select the IDP they wish to login with
    idp_selection_route="/login",
)
auth.register_provider(
    "IDP 1",
    token_endpoint_auth_method="client_secret_post",
    client_id="<my-client-id>",
    client_secret="<my-client-secret>",
    server_metadata_url="<my-idp-.well-known-configuration>",
)
auth.register_provider(
    "IDP 2",
    token_endpoint_auth_method="client_secret_post",
    client_id="<my-client-id2>",
    client_secret="<my-client-secret2>",
    server_metadata_url="<my-idp2-.well-known-configuration>",
)

@app.server.route("/login", methods=["GET", "POST"])
def login_handler():
    if request.method == "POST":
        idp = request.form.get("idp")
    else:
        idp = request.args.get("idp")

    if idp is not None:
        return redirect(url_for("oidc_login", idp=idp))

    return """<div>
        <form>
            <div>How do you wish to sign in:</div>
            <select name="idp">
                <option value="IDP 1">IDP 1</option>
                <option value="IDP 2">IDP 2</option>
            </select>
            <input type="submit" value="Login">
        </form>
    </div>"""


if __name__ == "__main__":
    app.run_server(debug=True)
```

#### Mixed Logins

To utilize OIDC and legacy logins, you need to provide a `idp_selection_route`, here is an example flow
using `Flask-Login`. 
The `login_user_callback` is also utilized so that you can configure the session cookies to 
be a similar format, or log the OIDC user into the `Flask-Login`

```python
from dash import Dash, html
from dash_auth import OIDCAuth
from flask import request, redirect, url_for, session
from flask_login import current_user, LoginManager, login_user, UserMixin

app = Dash(__name__)

login_manager = LoginManager()
login_manager.init_app(app.server)
class User(UserMixin):
    pass

@login_manager.user_loader
def user_loader(username):
    user = User()
    user.id = username
    return user

def all_login_method(user_info, idp=None):
    if idp:
        session["user"] = user_info
        session["idp"] = idp
        session['user']['groups'] = ['this', 'is', 'a', 'testing']
        user = User()
        user.id = user_info['email']
        login_user(user)
    else:
        user = User()
        user.id = user_info.get('user')
        login_user(user)
        session['user'] = {}
        session['user']['groups'] = ['nah']
        session['user']['email'] = user_info.get('user')
    return redirect(app.config.get("url_base_pathname") or "/")

def layout():
    if request:
        if current_user:
            try:
                return html.Div([
                    html.Div(f"Hello {current_user.id}!"),
                    html.Button(id='change_users', children='change restrictions'),
                    html.Button(id='test', children='you cant use me'),
                    html.A("Logout", href="/oidc/logout"),
                ])
            except:
                pass
        if 'user' in session:
            return html.Div([
                html.Div(f"""Hello {session['user'].get('email')}!
                        You have access to these groups: {session['user'].get('groups')}"""),
                html.Button(id='change_users', children='change restrictions'),
                html.Button(id='test', children='you cant use me'),
                html.A("Logout", href="/oidc/logout"),
            ])
    return html.Div([
        html.Div("Hello world!"),
        html.Button(id='change_users', children='change restrictions'),
        html.Button(id='test', children='you cant use me'),
        html.A("Logout", href="/oidc/logout"),
    ])

app.layout = layout

auth = OIDCAuth(
    app,
    secret_key="aStaticSecretKey!",
    # Set the route at which the user will select the IDP they wish to login with
    idp_selection_route="/login",
    login_user_callback=all_login_method
)
auth.register_provider(
    "IDP 1",
    token_endpoint_auth_method="client_secret_post",
    client_id="<my-client-id>",
    client_secret="<my-client-secret>",
    server_metadata_url="<my-idp-.well-known-configuration>",
)

@app.server.route("/login", methods=["GET", "POST"])
def login_handler():
    if request.method == 'POST':
        form_data = request.form
    else:
        form_data = request.args

    if form_data.get('user') and form_data.get('password'):
        return all_login_method(form_data)

    if form_data.get('IDP 1'):
        return redirect(url_for("oidc_login", idp='IDP 1'))

    return """<div>
        <form method="POST">
            <div>How do you wish to sign in:</div>
            <button type="submit" name="IDP 1" value="true">Microsoft</button>
            <div><input name="user"/>
            <input name="password"/></div>
            <input type="submit" value="Login">
        </form>
    </div>"""


if __name__ == "__main__":
    app.run_server(debug=True)
```

### User-group-based permissions

`dash_auth` provides a convenient way to secure parts of your app based on user groups.

The following utilities are defined:
* `list_groups`: Returns the groups of the current user, or None if the user is not authenticated.
* `check_groups`: Checks the current user groups against the provided list of groups.
  Available group checks are `one_of`, `all_of` and `none_of`.
  The function returns None if the user is not authenticated.
* `protected`: A function decorator that modifies the output if the user is unauthenticated
  or missing group permission.
* `protected_callback`: A callback that only runs if the user is authenticated
  and with the right group permissions.
* `protect_layout`: A function that will protect a layout similar to how `protected_callback` works.
  * eg `dash.register_page('test', path_template='/test/<test>', layout=protect_layout({'groups': ['testing']})(Layout))`
* `protect_layouts`: A function that will iterate through all pages and called `protect_layout` on the `layout`, 
  * passes `kwargs` to `protect_layout` if not already defined in the `layout`
  * eg `protect_layouts(missing_permissions_output=html.Div("I'm sorry, Dave, I'm afraid I can't do that"))`

NOTE: user info is stored in the session so make sure you define a secret_key on the Flask server
to use this feature.

If you wish to use this feature with BasicAuth, you will need to define the groups for individual
basicauth users:

```python
from dash_auth import BasicAuth

app = Dash(__name__)
USER_PWD = {
    "username": "password",
    "user2": "useSomethingMoreSecurePlease",
}
BasicAuth(
    app,
    USER_PWD,
    user_groups={"user1": ["group1", "group2"], "user2": ["group2"]},
    secret_key="Test!",
)

# You can also use a function to get user groups
def check_user(username, password):
    if username == "user1" and password == "password":
        return True
    if username == "user2" and password == "useSomethingMoreSecurePlease":
        return True
    return False

def get_user_groups(user):
    if user == "user1":
        return ["group1", "group2"]
    elif user == "user2":
        return ["group2"]
    return []

BasicAuth(
    app,
    auth_func=check_user,
    user_groups=get_user_groups,
    secret_key="Test!",
)
```

### User-based restrictions

`dash_auth` also allows for certain users to be restricted from content and callbacks,
even when they are assigned to a group which grants them access. 
This allows for more granular control. This is done by passing a list of users to `restricted_users`.
To check if a user is in the list, it needs the key from the `session["user"]` to compare, 
this is defaulted as `"email"`.

eg
```python
"""
where session['user'] = {'email': 'me@email.com'}
the below callback will not work
"""

@protected_callback(
    Output('test', 'children'),
    Input('test', 'n_clicks'),
    prevent_initial_call=True,
    restricted_users=['me@email.com']
)
def testing(n):
    return 'I was clicked'
```

### Additional flexibility

`dash_auth` has functions enabled for `groups` and `restricted_users`, this allows for dynamic 
control after application spinup.

When using the functions, the following dictionaries will be passed respectively as `kwargs` to 
the function you provide:
 - `group_lookup`: `{'path': '/test'}` => `pull_groups(path)`
 - `restricted_users_lookup`: `{'path': '/test'}` => `pull_users(path)`

### Restricting layouts

`dash_auth` by default will cater your page layouts that are in your public routes or where the user is authenticated.
However, it is possible to lock down layouts by passing these additional arguments to `OIDCAuth` or `BasicAuth` methods:

```python
auth_protect_layouts=True,
auth_protect_layouts_kwargs=dict(missing_permissions_output=html.Div('you cant get me')),
page_container='_pages_content'
```

Passing `auth_protect_layouts` tells the app to invoke the `protect_layouts` with the `public_routes` passed to 
not protect the layouts of public routes.
Passing `auth_protect_layouts_kwargs` is the same are the additional `kwargs` passed to the function
By default, the app will check any non-public callback that has the `pathname` as an input, 
when you pass `page_container` as the `id` of your container element for a page container,
it will only check the route if it is an output.
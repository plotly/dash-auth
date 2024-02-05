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
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

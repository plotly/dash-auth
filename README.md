## Dash Authorization and Login

![Lint](https://github.com/joschrag/dash-auth-async/actions/workflows/lint.yml/badge.svg)
![Typecheck](https://github.com/joschrag/dash-auth-async/actions/workflows/typecheck.yml/badge.svg)
[![codecov](https://codecov.io/gh/joschrag/dash-auth-async/branch/main/graph/badge.svg)](https://codecov.io/gh/joschrag/dash-auth-async)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/badge/type--checked-ty-blue)](https://github.com/astral-sh/ty)
[![PyPI](https://img.shields.io/pypi/v/dash-auth-async)](https://pypi.org/project/dash-auth-async/)
![Python](https://img.shields.io/pypi/pyversions/dash-auth-async)
![License](https://img.shields.io/pypi/l/dash-auth-async)

Maintained by [joschrag](https://github.com/joschrag/). Forked from [plotly/dash-auth](https://github.com/plotly/dash-auth) with the goal to add support for the new 4.x dash backends.

License: MIT

## Feature overview

How this fork compares to upstream [`dash-auth`](https://github.com/plotly/dash-auth). The headline difference is async: upstream is Flask-only, while `dash-auth-async` adds async callback support, the Quart and FastAPI backends, authenticated WebSocket callbacks, and a pluggable backend abstraction. 

| Capability | `dash-auth` (upstream) | `dash-auth-async` |
| --- | :---: | :---: |
| Flask backend | ✅ | ✅ |
| Quart backend | ❌ | ✅ |
| FastAPI backend | ❌ | ✅ |
| Custom backends | ❌ | ✅ <sup>1</sup> |
| Protected / public callbacks | ✅ | ✅ |
| Async callbacks | ❌ | ✅ <sup>2</sup> |
| Authenticated WebSocket callbacks | ❌ | ✅ <sup>3</sup> |
| Group-protected background callbacks | ❌ | ✅ <sup>4</sup> |

✅ supported · ❌ not supported

<sup>1</sup> `detect_backend` resolves Flask/Quart/FastAPI automatically; any other server is supported by supplying your own `Backend` instance.

<sup>2</sup> Supported on **every** backend, Flask included — you don't need Quart or FastAPI, just the `async` extra (bundled as `dash-auth-async[async]`, which pulls in `dash[async]`).

<sup>3</sup> Provided by the Quart and FastAPI backends only. WebSocket auth is a no-op on Flask, which has no WebSocket callback transport.

<sup>4</sup> `protected_callback(..., background=True)` checks the user's groups when the request arrives — on the start request and every poll — so a denied user gets the fallback output without a job ever being started. The job itself runs in a separate process with no session, which is why the check can't live inside it (upstream checks there, so a background job always sees "no user" and is denied). Needs a background manager, e.g. `dash[diskcache]`. These callbacks are refused over the WebSocket; Dash only sends background callbacks over HTTP.


For local testing, install [uv](https://docs.astral.sh/uv/getting-started/installation/), then install the dev dependencies and run individual tests:

```
uv sync
uv run pytest -k ba001
```

Note that Python 3.10 or greater is required.

## Usage

### Basic Authentication

To add basic authentication, add the following to your Dash app:

```python
from dash import Dash
from dash_auth_async import BasicAuth

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
from dash_auth_async import BasicAuth

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
from dash_auth_async import BasicAuth, add_public_routes

app = Dash(__name__)
USER_PWD = {
    "username": "password",
    "user2": "useSomethingMoreSecurePlease",
}
BasicAuth(app, USER_PWD, public_routes=["/"])

add_public_routes(app, public_routes=["/user/<user_id>/public"])
```

NOTE: If you are using server-side callbacks on your public routes, you should also use dash_auth_async's new `public_callback` rather than the default Dash callback.
Below is an example of a public route and callbacks on a multi-page Dash app using Dash's pages API:

*app.py*
```python
from dash import Dash, html, dcc, page_container
from dash_auth_async import BasicAuth

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
    app.run(debug=True)
```

---
*pages/home.py*
```python
from dash import Input, Output, html, register_page
from dash_auth_async import public_callback

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
from dash_auth_async import OIDCAuth

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

#### Running behind a reverse proxy

> **Behavior change.** Earlier versions rewrote the OIDC callback host from the
> client-supplied `X-Forwarded-Host` header. That header trust was **removed** — an
> attacker could set it to steer the `redirect_uri` handed to your IDP (auth-code leak /
> open redirect). The `redirect_uri` is now built **only** from the host and scheme of
> the incoming request.

The consequence: behind a proxy that terminates TLS or rewrites the host, the
`redirect_uri` comes out as `http://localhost:8050/...` and your IDP rejects it. To get
the real public host and scheme back, **restore it at the transport layer** — where the
trust can be bounded to your actual proxy, instead of trusting any client.

Two separate things to restore: **scheme** (http→https) and **host**. Most app servers
forward the scheme but **not** the host — `--forwarded-allow-ips` / `--proxy-headers`
only governs `X-Forwarded-Proto`/`-For`, never the host. So:

* **Scheme:** set `force_https_callback=True` on `OIDCAuth` (or pass the name of an env
  var that, when present, enables it). This covers the http→https half on every backend.
* **Host:** add proxy middleware that honours `X-Forwarded-Host`, sized to your real
  proxy-chain length:

| Backend | Server(s) | How to restore the host |
|---|---|---|
| **Flask** | gunicorn, waitress, mod_wsgi, … | `werkzeug` `ProxyFix` on the WSGI app (server-independent — gunicorn alone won't do the host) |
| **Quart** | hypercorn | `ProxyFixMiddleware(mode="modern", trusted_hops=N)` — restores host and scheme |
| **Quart / FastAPI** | uvicorn | uvicorn `--proxy-headers` does scheme only; add an `X-Forwarded-Host` ASGI middleware or have the proxy rewrite the `Host` header |

**Flask** (WSGI — gunicorn, waitress, …):

```python
from werkzeug.middleware.proxy_fix import ProxyFix

# Counts MUST equal your real proxy-chain length — setting them higher than the
# actual chain (or enabling this with no proxy) re-opens the spoofing hole.
app.server.wsgi_app = ProxyFix(app.server.wsgi_app, x_for=1, x_proto=1, x_host=1)
```

**Quart** (served by hypercorn) — wrap the ASGI app:

```python
from hypercorn.middleware import ProxyFixMiddleware

# trusted_hops MUST equal your real proxy-chain length (see warning below).
app.server.asgi_app = ProxyFixMiddleware(app.server.asgi_app, mode="modern", trusted_hops=1)
```

**FastAPI / Quart on uvicorn:** uvicorn restores the scheme (`--proxy-headers
--forwarded-allow-ips=...`) but **not** the host. Either have your proxy overwrite the
`Host` header with the public host, or add a small trusted ASGI middleware that copies
`X-Forwarded-Host` onto the `host` header — same `trusted_hops` discipline as above.

> ⚠️ Only restore proxy-header trust when a real proxy sets those headers, and set the
> hop counts to the actual chain length. A trusted-host middleware in front of *no*
> proxy lets a client spoof the host again — which is exactly the trust that was removed.

#### Multiple OIDC Providers

For multiple OIDC providers, you can use `register_provider` to add new ones after the OIDCAuth has been instantiated.

```python
from dash import Dash, html
from dash_auth_async import OIDCAuth
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
    app.run(debug=True)
```

### Async backends

#### Known Limitations

> **⚠️ WebSocket callbacks & auth:**
> Do **not** enable `websocket_callbacks=True`
> globally on an authenticated `use_pages` app. The global flag routes *every*
> callback — including Dash's built-in page-routing callback — over the WebSocket,
> which bypasses the HTTP `before_request` auth guard where the login challenge is
> issued. Navigating to a protected page then hangs (the socket closes with `4401`
> and reconnect-loops) instead of prompting for login — the prompt appears only after
> a full page reload. Opt **individual** streaming callbacks into `websocket=True`
> instead, so routing and login stay on HTTP.


#### Quart (async) Backend

`dash-auth-async` supports [Dash's Quart backend](https://dash.plotly.com/) for fully async request handling.
Install the `quart` extra to pull in the required dependencies:

```
pip install dash-auth-async[quart]
```

Then pass `backend="quart"` when creating your Dash app. The auth setup is identical
to the Flask examples above — no code changes required beyond the backend flag.

##### BasicAuth with Quart

```python
from dash import Dash
from dash_auth_async import BasicAuth

app = Dash(__name__, backend="quart")

BasicAuth(app, {"admin": "admin", "viewer": "viewer123"})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)
```

##### OIDCAuth with Quart

```python
import os
from dash import Dash, html
from dash_auth_async import OIDCAuth

app = Dash(__name__, backend="quart")

app.layout = html.Div([
    html.H2("OIDCAuth + Quart"),
    html.A("Logout", href="/oidc/logout"),
])

auth = OIDCAuth(app, secret_key="aStaticSecretKey!")
auth.register_provider(
    "myidp",
    client_id=os.environ["OIDC_CLIENT_ID"],
    client_secret=os.environ["OIDC_CLIENT_SECRET"],
    server_metadata_url=os.environ["OIDC_METADATA_URL"],
    token_endpoint_auth_method="client_secret_post",
    client_kwargs={"scope": "openid email profile"},
)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)
```

> **Note:** The Quart backend requires Dash >= 4.2.0 and Python >= 3.10.

#### FastAPI (async) Backend

`dash-auth-async` supports [Dash's FastAPI backend](https://dash.plotly.com/) too.
Install the `fastapi` extra to pull in the required dependencies:

```
pip install dash-auth-async[fastapi]
```

Then pass `backend="fastapi"` when creating your Dash app. `BasicAuth` and
`OIDCAuth` work exactly as on Flask/Quart — no code changes beyond the backend flag.

##### BasicAuth with FastAPI

```python
from dash import Dash
from dash_auth_async import BasicAuth

app = Dash(__name__, backend="fastapi")

BasicAuth(
    app,
    {"admin": "admin", "viewer": "viewer123"},
    secret_key="aStaticSecretKey!",  # enables sessions (SessionMiddleware)
)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)
```

##### OIDCAuth with FastAPI

```python
import os
from dash import Dash, html
from dash_auth_async import OIDCAuth

app = Dash(__name__, backend="fastapi")

app.layout = html.Div([
    html.H2("OIDCAuth + FastAPI"),
    html.A("Logout", href="/oidc/logout"),
])

auth = OIDCAuth(app, secret_key="aStaticSecretKey!")
auth.register_provider(
    "myidp",
    client_id=os.environ["OIDC_CLIENT_ID"],
    client_secret=os.environ["OIDC_CLIENT_SECRET"],
    server_metadata_url=os.environ["OIDC_METADATA_URL"],
    token_endpoint_auth_method="client_secret_post",
    client_kwargs={"scope": "openid email profile"},
)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True)
```

Notes:

- A `secret_key` installs Starlette's `SessionMiddleware` automatically. If you
  add your own `SessionMiddleware`, `dash-auth-async` defers to it.
- `Auth`/`OIDCAuth` must be constructed before the server starts serving
  (Starlette forbids adding middleware after startup) — the normal usage pattern.
- OIDC uses authlib's official `starlette_client`; no extra client module required.

> The FastAPI backend requires Dash >= 4.2.0 and Python >= 3.10.

### User-group-based permissions

`dash_auth_async` provides a convenient way to secure parts of your app based on user groups.

The following utilities are defined:
* `list_groups`: Returns the groups of the current user, or None if the user is not authenticated.
* `check_groups`: Checks the current user groups against the provided list of groups.
  Available group checks are `one_of`, `all_of` and `none_of`.
  The function returns None if the user is not authenticated.
* `protected`: A function decorator that modifies the output if the user is unauthenticated
  or missing group permission.
* `protected_callback`: A callback that only runs if the user is authenticated
  and with the right group permissions.

NOTE: user info is stored in the session so make sure you define a secret_key on the server
to use this feature.

If you wish to use this feature with BasicAuth, you will need to define the groups for individual
basicauth users:

```python
from dash_auth_async import BasicAuth

app = Dash(__name__)
USER_PWD = {
    "username": "password",
    "user2": "useSomethingMoreSecurePlease",
}
BasicAuth(
    app,
    USER_PWD,
    user_groups={"username": ["group1", "group2"], "user2": ["group2"]},
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

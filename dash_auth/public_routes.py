import inspect
import os

from dash import Dash, callback
from dash._callback import GLOBAL_CALLBACK_MAP
from dash import get_app
from flask import Flask
from werkzeug.datastructures import ImmutableDict
from werkzeug.routing import Map, Rule

# Add PUBLIC_ROUTES in the default Flask config
DASH_PUBLIC_ASSETS_EXTENSIONS = "js,css"
BASE_PUBLIC_ROUTES = [
    f"/assets/<path:path>.{ext}"
    for ext in os.getenv(
        "DASH_PUBLIC_ASSETS_EXTENSIONS",
        DASH_PUBLIC_ASSETS_EXTENSIONS,
    ).split(",")
] + [
    "/_dash-component-suites/<path:path>",
    "/_dash-layout",
    "/_dash-dependencies",
    "/_favicon.ico",
    "/_reload-hash",
]
PUBLIC_ROUTES = "PUBLIC_ROUTES"
PUBLIC_CALLBACKS = "PUBLIC_CALLBACKS"

default_config = Flask.default_config
Flask.default_config = ImmutableDict(
    **default_config,
    **{
        PUBLIC_ROUTES: Map([]).bind(""),
        PUBLIC_CALLBACKS: [],
    },
)


def add_public_routes(app: Dash, routes: list):
    """Add routes to the public routes list.

    The routes passed should follow the Flask route syntax.
    e.g. "/login", "/user/<user_id>/public"

    Some routes are made public by default:
    * All dash scripts (_dash-dependencies, _dash-component-suites/**)
    * All dash mechanics routes (_dash-layout, _reload-hash)
    * All assets with extension .css, .js, .svg, .jpg, .png, .gif, .webp
      Note: you can modify the extension by setting the
      `DASH_ASSETS_PUBLIC_EXTENSIONS` envvar (comma-separated list of
      extensions, e.g. "js,css,svg").
    * The favicon

    If you use callbacks on your public routes, you should use dash_auth's
    `public_callback` rather than the standard dash callback.

    :param app: Dash app
    :param routes: list of public routes to be added
    """

    # Make a copy to avoid modifying the default value inplace
    existing_rules: list[Rule] = app.server.config[PUBLIC_ROUTES].map._rules
    public_routes = Map([]).bind("")

    if not existing_rules:
        routes = BASE_PUBLIC_ROUTES + routes
    else:
        routes = [r.rule for r in existing_rules] + routes

    for route in routes:
        public_routes.map.add(Rule(route))

    app.server.config[PUBLIC_ROUTES] = public_routes


def public_callback(*callback_args, **callback_kwargs):
    """Public Dash callback.

    This works by adding the callback id (from the callback map) to a list
    of whitelisted callbacks in the Flask server's config.

    :param **: all args and kwargs passed to a dash callback
    """

    def decorator(func):

        wrapped_func = callback(*callback_args, **callback_kwargs)(func)
        callback_id = next(
            (
                k for k, v in GLOBAL_CALLBACK_MAP.items()
                if inspect.getsource(v["callback"]) == inspect.getsource(func)
            ),
            None,
        )
        try:
            app = get_app()
            app.server.config[PUBLIC_CALLBACKS].append(callback_id)
        except Exception:
            print(
                "Could not set up the public callback as the Dash object "
                "has not yet been instantiated."
            )

        def wrap(*args, **kwargs):
            return wrapped_func(*args, **kwargs)

        return wrap

    return decorator

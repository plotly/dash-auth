import inspect
import os

from dash import Dash, callback
from dash._callback import GLOBAL_CALLBACK_MAP
from dash import get_app
from werkzeug.routing import Map, MapAdapter, Rule

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


def get_url_base(app: Dash) -> str:
    """Return the URL prefix configured for the Dash app (e.g. '/app/').

    Returns '' when no prefix is configured. Checks url_base_pathname first,
    then requests_pathname_prefix, then routes_pathname_prefix. In normal Dash
    usage these three values are always kept in sync by Dash itself; the
    fallback order only matters in advanced deployments.

    This reads from app.config at call time, so it must be invoked after the
    Dash app's URL config is fully initialised. In particular, calling
    add_public_routes() before url_base_pathname is set on the app will store
    routes without the prefix and they will never match at request time.
    """
    return (
        app.config.get("url_base_pathname")
        or app.config.get("routes_pathname_prefix")
        or ""
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

    public_routes = get_public_routes(app)
    url_base = get_url_base(app)

    if not public_routes.map._rules:
        routes = BASE_PUBLIC_ROUTES + routes

    for route in routes:
        if url_base and not route.startswith(url_base):
            route = url_base.rstrip("/") + route
        public_routes.map.add(Rule(route))

    app.server.config[PUBLIC_ROUTES] = public_routes


def public_callback(*callback_args, **callback_kwargs):
    """Public Dash callback.

    This works by adding the callback id (from the callback map) to a list
    of allowlisted callbacks in the Flask server's config.

    :param **: all args and kwargs passed to a dash callback
    """

    def decorator(func):

        wrapped_func = callback(*callback_args, **callback_kwargs)(func)
        callback_id = next(
            (
                k
                for k, v in GLOBAL_CALLBACK_MAP.items()
                if inspect.getsource(v["callback"]) == inspect.getsource(func)
            ),
            None,
        )
        try:
            app = get_app()
            app.server.config[PUBLIC_CALLBACKS] = get_public_callbacks(app) + [
                callback_id
            ]
        except Exception:
            print(
                "Could not set up the public callback as the Dash object "
                "has not yet been instantiated."
            )

        def wrap(*args, **kwargs):
            return wrapped_func(*args, **kwargs)

        return wrap

    return decorator


def get_public_routes(app: Dash) -> MapAdapter:
    """Retrieve the public routes."""
    return app.server.config.get(PUBLIC_ROUTES, Map([]).bind(""))


def get_public_callbacks(app: Dash) -> list:
    """Retrieve the public callbacks ids."""
    return app.server.config.get(PUBLIC_CALLBACKS, [])

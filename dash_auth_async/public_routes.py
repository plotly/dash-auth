"""Public route and callback registration for unauthenticated access."""

import os

from dash import Dash, callback, get_app

# create_callback_id is the same helper Dash uses internally to key its
# callback map; no public API equivalent exists.
from dash._utils import create_callback_id  # noqa: PLC2701
from dash.dependencies import handle_callback_args
from werkzeug.routing import Map, MapAdapter, Rule

from .backends import detect_backend

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

    If you use callbacks on your public routes, you should use dash_auth_async's
    `public_callback` rather than the standard dash callback.

    :param app: Dash app
    :param routes: list of public routes to be added
    """
    public_routes = get_public_routes(app)
    url_base = get_url_base(app)

    if not public_routes.map._rules:
        routes = BASE_PUBLIC_ROUTES + routes

    for route in routes:
        full_route = route
        if url_base and not full_route.startswith(url_base):
            full_route = url_base.rstrip("/") + full_route
        public_routes.map.add(Rule(full_route))

    detect_backend(app.server).store_config(app.server, PUBLIC_ROUTES, public_routes)


def public_callback(*callback_args, **callback_kwargs):
    """Public Dash callback.

    This works by adding the callback id (from the callback map) to a list
    of whitelisted callbacks in the Flask server's config.

    :param **: all args and kwargs passed to a dash callback

    Returns:
        A decorator that registers the public Dash callback.
    """

    def decorator(func):
        wrapped_func = callback(*callback_args, **callback_kwargs)(func)
        # Derive the callback id straight from the output specs, exactly as
        # Dash does internally (create_callback_id). This is deterministic and
        # independent of GLOBAL_CALLBACK_MAP state -- unlike diffing the map,
        # which yields no new key when the same output id was already
        # registered (re-runs, or several apps sharing one process), and unlike
        # source-text comparison, which mis-whitelists callbacks sharing a body
        # and raises on lambdas/REPL-defined functions.
        output, inputs, _state, _prevent = handle_callback_args(
            callback_args, callback_kwargs
        )
        callback_id = create_callback_id(output, inputs, no_output=not output)
        try:
            app = get_app()
            backend = detect_backend(app.server)
            backend.store_config(
                app.server,
                PUBLIC_CALLBACKS,
                [*backend.read_config(app.server, PUBLIC_CALLBACKS, []), callback_id],
            )
        except Exception:
            print(
                "Could not set up the public callback as the Dash object "
                "has not yet been instantiated."
            )

        # Return Dash's result as-is: a plain forwarding def would erase the
        # coroutine/generator kind of the user's function.
        return wrapped_func

    return decorator


def get_public_routes(app: Dash) -> MapAdapter:
    """Retrieve the public routes.

    Returns:
        The MapAdapter holding the app's registered public routes.
    """
    return detect_backend(app.server).read_config(
        app.server, PUBLIC_ROUTES, Map([]).bind("")
    )


def get_public_callbacks(app: Dash) -> list:
    """Retrieve the public callbacks ids.

    Returns:
        The list of whitelisted public callback ids.
    """
    return detect_backend(app.server).read_config(app.server, PUBLIC_CALLBACKS, [])

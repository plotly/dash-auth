from .public_routes import add_public_routes, public_callback
from .basic_auth import BasicAuth
from .group_protection import (
    list_groups, check_groups, protected, protected_callback
)
# oidc auth requires authlib, install with `pip install dash-auth[oidc]`
try:
    from .oidc_auth import OIDCAuth, get_oauth
except ModuleNotFoundError:
    pass
from .version import __version__


__all__ = [
    "add_public_routes",
    "check_groups",
    "list_groups",
    "get_oauth",
    "protected",
    "protected_callback",
    "public_callback",
    "BasicAuth",
    "OIDCAuth",
    "__version__",
]

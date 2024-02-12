import logging
import re
from numbers import Number
from typing import Callable, List, Literal, Optional, Union

import dash
from dash.development.base_component import Component as DashComponent
from dash.exceptions import PreventUpdate
from flask import session, has_request_context


ComponentPart = Union[DashComponent, str, Number]
Component = Union[ComponentPart, List[ComponentPart]]
OutputVal = Union[Callable[[], Component], Component]
CheckType = Literal["one_of", "all_of", "none_of"]


def list_groups(
    *,
    groups_key: str = "groups",
    groups_str_split: str = None,
) -> Optional[List[str]]:
    """List all the groups the user belongs to.

    :param groups_key: Groups key in the user data saved in the Flask session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string
    :return: None or list[str]:
        * None if the user is not authenticated
        * list[str] otherwise
    """
    if not has_request_context() or "user" not in session:
        return None

    user_groups = session.get("user", {}).get(groups_key, [])
    # Handle cases where groups are ,- or ;-separated string,
    # may depend on OIDC provider
    if isinstance(user_groups, str) and groups_str_split is not None:
        user_groups = re.split(groups_str_split, user_groups)
    return user_groups


def check_groups(
    groups: Optional[List[str]] = None,
    *,
    groups_key: str = "groups",
    groups_str_split: str = None,
    check_type: CheckType = "one_of",
) -> Optional[bool]:
    """Check whether the current user is authenticated
    and has the specified groups.

    :param groups: List of groups to check for with check_type
    :param groups_key: Groups key in the user data saved in the Flask session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string
    :param check_type: Type of check to perform.
        Either "one_of", "all_of" or "none_of"
    :return: None or boolean:
        * None if the user is not authenticated
        * True if the user is authenticated and has the right permissions
        * False if the user is authenticated but does not have
          the right permissions
    """
    user_groups = list_groups(
        groups_key=groups_key,
        groups_str_split=groups_str_split,
    )

    if user_groups is None:
        # User is not authenticated
        return None

    if groups is None:
        return True

    if check_type == "one_of":
        return bool(set(user_groups).intersection(groups))
    if check_type == "all_of":
        return all(group in user_groups for group in groups)
    if check_type == "none_of":
        return not any(group in user_groups for group in groups)

    raise ValueError(f"Invalid check_type: {check_type}")


def protected(
    unauthenticated_output: Optional[OutputVal] = None,
    *,
    missing_permissions_output: Optional[OutputVal] = None,
    groups: Optional[List[str]] = None,
    groups_key: str = "groups",
    groups_str_split: str = None,
    check_type: CheckType = "one_of",
) -> Callable:
    """Decorate a function or output to alter it depending on the state
    of authentication and permissions.

    :param unauthenticated_output: Output when the user is not authenticated.
        Note: needs to be a function with no argument or
        a collection of Dash components.
    :param missing_permissions_output: Output when the user is authenticated
        but does not have the right permissions.
        It defaults to unauthenticated_output when not set.
        Note: needs to be a function with no argument or
        a collection of Dash components.
    :param groups: List of authorized user groups. If no groups are passed,
        the decorator will only check whether the user is authenticated.
    :param groups_key: Groups key in the user data saved in the Flask session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string
    :param check_type: Type of check to perform.
        Either "one_of", "all_of" or "none_of"
    """
    if unauthenticated_output is None:
        unauthenticated_output = ""

    if missing_permissions_output is None:
        missing_permissions_output = unauthenticated_output

    def decorator(output: OutputVal):
        def wrap(*args, **kwargs):
            def process_output(output, *args, **kwargs):
                if isinstance(output, Callable):
                    return output(*args, **kwargs)
                return output

            authorized = check_groups(
                groups=groups,
                groups_key=groups_key,
                groups_str_split=groups_str_split,
                check_type=check_type,
            )
            if authorized is None:
                return process_output(unauthenticated_output)
            if authorized:
                return process_output(output, *args, **kwargs)
            return process_output(missing_permissions_output)

        if isinstance(output, Callable):
            return wrap
        return wrap()

    return decorator


def protected_callback(
    *callback_args,
    groups: List[str] = None,
    groups_key: str = "groups",
    groups_str_split: str = None,
    check_type: CheckType = "one_of",
    **callback_kwargs,
) -> Callable:
    """Protected Dash callback.

    :param **: all args and kwargs passed to a dash callback
    :param groups: List of authorized user groups
    :param groups_key: Groups key in the user data saved in the Flask session
        e.g. session["user"] == {"email": "a.b@mail.com", "groups": ["admin"]}
    :param groups_str_split: Used to split groups if provided as a string
    :param check_type: Type of check to perform.
        Either "one_of", "all_of" or "none_of"
    """

    def decorator(func):
        def prevent_unauthenticated():
            logging.info(
                "A user tried to run %s without being authenticated.",
                func.__name__,
            )
            raise PreventUpdate

        def prevent_unauthorised():
            logging.info(
                "%s tried to run %s but did not have the right permissions.",
                session["user"]["email"],
                func.__name__,
            )
            raise PreventUpdate

        wrapped_func = dash.callback(*callback_args, **callback_kwargs)(
            protected(
                unauthenticated_output=prevent_unauthenticated,
                missing_permissions_output=prevent_unauthorised,
                groups=groups,
                groups_key=groups_key,
                groups_str_split=groups_str_split,
                check_type=check_type,
            )(func)
        )

        def wrap(*args, **kwargs):
            return wrapped_func(*args, **kwargs)

        return wrap

    return decorator

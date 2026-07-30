import flask

from dash import hooks

@hooks.custom_data("user")
def custom_data_func(_ctx):
    try:
        cu = flask.session["user"]
    except AttributeError as e:
        cu = {}
    return cu

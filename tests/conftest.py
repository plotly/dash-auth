from typing import Any

import dash.testing.application_runners as _runners
import pytest
from dash._callback import GLOBAL_CALLBACK_LIST, GLOBAL_CALLBACK_MAP

from dash_auth_async import backends


def _stop_quart_gracefully(runner) -> bool:
    """Shut down a quart-backend dash test server via its own shutdown event.

    ThreadedRunner.stop() kills server threads with an async SystemExit,
    which abandons hypercorn's connections mid-flight; on Windows the
    proactor loop's close() then waits forever for the orphaned overlapped
    I/O and pytest hangs in teardown (browser stays open). Dash's Quart
    backend has a graceful path - serve(shutdown_trigger=...) awaits
    backend._ws_shutdown_event - but only the main-thread signal handler
    ever sets it. Set it here, thread-safely, on the server's own loop.

    Returns True if the server thread exited; False means fall back to
    the original kill-based stop.
    """
    # dash<4.2.0 ThreadedRunner has no _app attribute (and no quart backend).
    backend_server = getattr(getattr(runner, "_app", None), "backend", None)
    event = getattr(backend_server, "_ws_shutdown_event", None)
    if event is None:
        return False
    # The asyncio.Event binds its loop on first await (in shutdown_trigger),
    # so its private _loop is the hypercorn loop in the server thread.
    loop = getattr(event, "_loop", None)
    if loop is None or loop.is_closed():
        return False
    try:
        loop.call_soon_threadsafe(event.set)
    except (RuntimeError, AttributeError):
        return False
    runner.thread.join(timeout=runner.stop_timeout)
    return not runner.thread.is_alive()


def _stop_fastapi_gracefully(runner) -> bool:
    """Shut down a fastapi-backend dash test server via uvicorn's should_exit.

    Dash's FastAPI backend stores the uvicorn Server on the Dash app as
    ``_uvicorn_server`` when run threaded (_fastapi.py:384). Setting
    ``should_exit`` lets uvicorn's serve loop return so the thread exits
    cleanly instead of being killed mid-flight.

    Returns True if the server thread exited; False means fall back to the
    original kill-based stop.
    """
    dash_app = getattr(runner, "_app", None)
    server = getattr(dash_app, "_uvicorn_server", None)
    if server is None:
        return False
    server.should_exit = True
    runner.thread.join(timeout=runner.stop_timeout)
    return not runner.thread.is_alive()


_original_init = _runners.BaseDashRunner.__init__


def _init_with_ipv4_host(
    self: Any, keep_open, stop_timeout, scheme="http", host="127.0.0.1"
) -> None:
    """Build server URLs from 127.0.0.1 instead of localhost.

    The dash servers bind to 127.0.0.1 (IPv4) only, but the runners
    default to host="localhost". On Windows, localhost resolves to ::1
    first and each fresh connection waits ~2s for the IPv6 attempt to
    time out before falling back to IPv4 - a flat 2s tax on every
    requests.get/startup poll, which dominated the suite's runtime.
    """
    _original_init(self, keep_open, stop_timeout, scheme=scheme, host=host)


_runners.BaseDashRunner.__init__ = _init_with_ipv4_host  # type: ignore


_original_stop = _runners.ThreadedRunner.stop


def _stop_with_graceful_async(self: Any) -> Any:
    if _stop_quart_gracefully(self) or _stop_fastapi_gracefully(self):
        self._app = None
        self.started = False
        return
    return _original_stop(self)


_runners.ThreadedRunner.stop = _stop_with_graceful_async  # type: ignore


@pytest.fixture
def reset_active_backend():
    """Keep the module-level active backend from leaking between tests.

    Teardown-only: any test that mutates ``backends._active_backend`` (directly
    via ``set_active_backend`` or indirectly by constructing an ``Auth``
    subclass, whose ``__init__`` calls it) must opt in so it resets the global
    afterwards. Modules that touch the backend do so with a module-level
    ``pytestmark = pytest.mark.usefixtures("reset_active_backend")``.
    """
    yield
    backends._active_backend = None


@pytest.fixture
def isolated_callback_registry():
    """Drop callbacks registered by the test from Dash's process-global registry.

    Streaming callbacks left behind make every later Dash app without shared
    storage fail at setup (dash validates all global callbacks), so they must
    not leak into other tests.
    """
    saved_map = dict(GLOBAL_CALLBACK_MAP)
    saved_list = list(GLOBAL_CALLBACK_LIST)
    yield
    GLOBAL_CALLBACK_MAP.clear()
    GLOBAL_CALLBACK_MAP.update(saved_map)
    GLOBAL_CALLBACK_LIST[:] = saved_list

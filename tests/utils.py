from contextlib import contextmanager
import json
import sys
import time


def clean_history(driver, domains):
    temp = driver.get_location()
    for domain in domains:
        driver.open(domain)
        driver.delete_all_visible_cookies()
    driver.open(temp)


def switch_windows(driver):
    new_window_handle = None
    while not new_window_handle:
        for handle in driver.window_handles:
            if handle != driver.current_window_handle:
                new_window_handle = handle
                break
    driver.switch_to.window(new_window_handle)
    return new_window_handle


class WaitForTimeout(Exception):
    """This should only be raised inside the `wait_for` function."""
    pass


def assert_clean_console(TestClass):
    def assert_no_console_errors(TestClass):
        TestClass.assertEqual(
            TestClass.driver.execute_script(
                'return window.tests.console.error.length'
            ),
            0
        )

    def assert_no_console_warnings(TestClass):
        TestClass.assertEqual(
            TestClass.driver.execute_script(
                'return window.tests.console.warn.length'
            ),
            0
        )

    assert_no_console_warnings(TestClass)
    assert_no_console_errors(TestClass)


@contextmanager
def captured_output(f):
    old_out = sys.stdout
    try:
        sys.stdout = f
        yield sys.stdout
    finally:
        sys.stdout = old_out

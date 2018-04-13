from __future__ import absolute_import
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
import importlib
import multiprocessing
import requests
import time
import unittest
from selenium import webdriver
import sys
import os

from .utils import assert_clean_console, switch_windows

TIMEOUT = 60


class IntegrationTests(unittest.TestCase):
    def wait_for_element_by_css_selector(self, selector):
        start_time = time.time()
        while time.time() < start_time + TIMEOUT:
            try:
                return self.driver.find_element_by_css_selector(selector)
            except Exception as e:
                pass
            time.sleep(0.25)
        raise e

    def wait_for_text_to_equal(self, selector, assertion_text):
        start_time = time.time()
        while time.time() < start_time + TIMEOUT:
            el = self.wait_for_element_by_css_selector(selector)
            try:
                return self.assertEqual(el.text, assertion_text)
            except Exception as e:
                pass
            time.sleep(0.25)
        raise e

    @classmethod
    def setUpClass(cls):
        super(IntegrationTests, cls).setUpClass()
        cls.driver = webdriver.Chrome()

    @classmethod
    def tearDownClass(cls):
        super(IntegrationTests, cls).tearDownClass()
        cls.driver.quit()

    def setUp(self):
        super(IntegrationTests, self).setUp()
        self.driver = webdriver.Chrome()

    def tearDown(self):
        super(IntegrationTests, self).tearDown()
        time.sleep(5)
        self.server_process.terminate()
        time.sleep(5)
        self.driver.quit()

    def startServer(self, app, skip_visit=False):
        def run():
            app.scripts.config.serve_locally = True
            app.run_server(
                port=8050,
                debug=False,
                processes=2
            )

        # Run on a separate process so that it doesn't block
        self.server_process = multiprocessing.Process(target=run)
        self.server_process.start()
        time.sleep(15)

        # Visit the dash page
        if not skip_visit:
            self.driver.get('http://localhost:8050{}'.format(
                app.config['routes_pathname_prefix'])
            )

        time.sleep(0.5)

        # Inject an error and warning logger
        logger = '''
        window.tests = {};
        window.tests.console = {error: [], warn: [], log: []};

        var _log = console.log;
        var _warn = console.warn;
        var _error = console.error;

        console.log = function() {
            window.tests.console.log.push({method: 'log',
                                           arguments: arguments});
            return _log.apply(console, arguments);
        };

        console.warn = function() {
            window.tests.console.warn.push({method: 'warn',
                                            arguments: arguments});
            return _warn.apply(console, arguments);
        };

        console.error = function() {
            window.tests.console.error.push({method: 'error',
                                             arguments: arguments});
            return _error.apply(console, arguments);
        };
        '''
        self.driver.execute_script(logger)

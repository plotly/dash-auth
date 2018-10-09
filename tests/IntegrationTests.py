from __future__ import absolute_import

import threading

import flask
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import importlib
import multiprocessing
import requests
import time
import unittest
from selenium import webdriver
import sys
import os

from selenium.webdriver.support.wait import WebDriverWait

from .utils import assert_clean_console, switch_windows

TIMEOUT = 120
from selenium.webdriver.support import expected_conditions as EC


class IntegrationTests(unittest.TestCase):
    def wait_for_element_by_css_selector(self, selector):
        return WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )

    def wait_for_text_to_equal(self, selector, assertion_text):
        return WebDriverWait(self.driver, 10).until(
            EC.text_to_be_present_in_element((By.CSS_SELECTOR, selector),
                                             assertion_text)
        )

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
                processes=2,
                threaded=False
            )

        # Run on a separate process so that it doesn't block
        self.server_process = multiprocessing.Process(target=run)
        self.server_process.start()
        time.sleep(15)

        # Visit the dash page
        if not skip_visit:
            self.driver.get('http://localhost:8050{}'.format(
                app.config['requests_pathname_prefix'])
            )
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, 'react-entry-point')))

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

from __future__ import absolute_import

import threading

import flask
from selenium.webdriver.common.by import By
import requests
import time
import unittest
from selenium import webdriver

from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

TIMEOUT = 48


class IntegrationTests(unittest.TestCase):
    def wait_for_element_by_css_selector(self, selector):
        return WebDriverWait(self.driver, TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )

    def wait_for_text_to_equal(self, selector, assertion_text):
        return WebDriverWait(self.driver, TIMEOUT).until(
            EC.text_to_be_present_in_element((By.CSS_SELECTOR, selector),
                                             assertion_text)
        )

    def wait_for_element_to_be_clickable(self, name):
        return WebDriverWait(self.driver, TIMEOUT).until(
            EC.element_to_be_clickable((By.NAME, name))
        )

    @classmethod
    def setUpClass(cls):
        super(IntegrationTests, cls).setUpClass()

    def setUp(self):
        options = webdriver.ChromeOptions()
        options.headless = True
        options.add_argument('no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        self.driver = webdriver.Chrome(options=options)

    def tearDown(self):
        super(IntegrationTests, self).tearDown()
        time.sleep(2)
        requests.get('http://localhost:8050/stop')
        self.driver.close()
        time.sleep(4)
        self.server_thread.join()

    def startServer(self, app, skip_visit=False):
        def run():
            app.scripts.config.serve_locally = True
            app.run_server(
                port=8050,
                debug=False,
                threaded=True
            )

        # Run on a separate thread so that it doesn't block

        @app.server.route('/stop')
        def _stop():
            stopper = flask.request.environ['werkzeug.server.shutdown']
            stopper()
            return 'stop'

        self.server_thread = threading.Thread(target=run)
        self.server_thread.start()
        time.sleep(2)

        # Visit the dash page
        if not skip_visit:
            self.driver.get('http://localhost:8050{}'.format(
                app.config['requests_pathname_prefix'])
            )
            WebDriverWait(self.driver, TIMEOUT).until(
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

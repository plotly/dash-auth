from __future__ import absolute_import

import multiprocessing
import os
import platform
import threading

import flask
from selenium.webdriver.common.by import By
import requests
import time
import unittest
from selenium import webdriver

from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

TIMEOUT = 10


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

    @classmethod
    def setUpClass(cls):
        super(IntegrationTests, cls).setUpClass()

    def setUp(self):
        options = webdriver.ChromeOptions()
        # options.headless = True
        self.driver = webdriver.Chrome(options=options)

    def tearDown(self):
        if platform.system() == 'Windows':
            requests.get('http://localhost:8050/stop')
        else:
            self.server_process.terminate()
        self.driver.quit()
        time.sleep(1)

    def startServer(self, app, skip_visit=False):
        """

        :param app:
        :type app: dash.Dash
        :return:
        """
        if 'DASH_TEST_PROCESSES' in os.environ:
            processes = int(os.environ['DASH_TEST_PROCESSES'])
        else:
            processes = 4

        def run():
            app.scripts.config.serve_locally = True
            app.css.config.serve_locally = True
            app.run_server(
                port=8050,
                debug=False,
                processes=processes,
                threaded=False,
            )

        def run_windows():
            app.scripts.config.serve_locally = True
            app.css.config.serve_locally = True

            @app.server.route('/stop')
            def _stop_server_windows():
                stopper = flask.request.environ['werkzeug.server.shutdown']
                stopper()
                return 'stop'

            app.run_server(
                port=8050,
                debug=False,
                threaded=True
            )

        # Run on a separate process so that it doesn't block

        system = platform.system()
        if system == 'Windows':
            # multiprocess can't pickle an inner func on windows (closure are not serializable by default on windows)
            self.server_thread = threading.Thread(target=run_windows)
            self.server_thread.start()
        else:
            self.server_process = multiprocessing.Process(target=run)
            self.server_process.start()
        time.sleep(2)

        # Visit the dash page
        if not skip_visit:
            self.driver.get('http://localhost:8050{}'.format(
                app.config['requests_pathname_prefix'])
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
               window.tests.console.log.push({method: 'log', arguments: arguments});
               return _log.apply(console, arguments);
           };

           console.warn = function() {
               window.tests.console.warn.push({method: 'warn', arguments: arguments});
               return _warn.apply(console, arguments);
           };

           console.error = function() {
               window.tests.console.error.push({method: 'error', arguments: arguments});
               return _error.apply(console, arguments);
           };
           '''
        self.driver.execute_script(logger)
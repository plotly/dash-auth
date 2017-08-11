from __future__ import absolute_import
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
import importlib
import multiprocessing
import time
import unittest


class IntegrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super(IntegrationTests, cls).setUpClass()

    @classmethod
    def tearDownClass(cls):
        super(IntegrationTests, cls).tearDownClass()

    def setUp(self):
        pass

    def tearDown(self):
        time.sleep(2)
        self.server_process.terminate()
        time.sleep(5)


    def startServer(self, app):
        def run():
            app.scripts.config.serve_locally = True
            app.run_server(
                port=8050,
                debug=False,
                threaded=True
            )

        # Run on a separate process so that it doesn't block
        self.server_process = multiprocessing.Process(target=run)
        self.server_process.start()
        time.sleep(0.5)

        # Visit the dash page
        self.driver.get('http://localhost:8050')
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

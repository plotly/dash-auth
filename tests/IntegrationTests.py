from __future__ import absolute_import
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
import importlib
import multiprocessing
import requests
import time
import unittest
from selenium import webdriver
import percy

from .utils import assert_clean_console, invincible, switch_windows, wait_for

class IntegrationTests(unittest.TestCase):

    def percy_snapshot(cls, name=''):
        snapshot_name = '{} - {}'.format(name, sys.version_info)
        print(snapshot_name)
        cls.percy_runner.snapshot(
            name=snapshot_name
        )

    @classmethod
    def setUpClass(cls):
        super(IntegrationTests, cls).setUpClass()
        cls.driver = webdriver.Chrome()

        loader = percy.ResourceLoader(
          webdriver=cls.driver
        )
        cls.percy_runner = percy.Runner(loader=loader)

        cls.percy_runner.initialize_build()

    @classmethod
    def tearDownClass(cls):
        super(IntegrationTests, cls).tearDownClass()
        cls.driver.quit()
        cls.percy_runner.finalize_build()

    def setUp(self):
        super(IntegrationTests, self).setUp()
        self.driver = webdriver.Chrome()

        def wait_for_element_by_id(id):
            wait_for(lambda: None is not invincible(
                lambda: self.driver.find_element_by_id(id)
            ))
            return self.driver.find_element_by_id(id)
        self.wait_for_element_by_id = wait_for_element_by_id

        def wait_for_element_by_css_selector(css_selector):
            wait_for(lambda: None is not invincible(
                lambda: self.driver.find_element_by_css_selector(css_selector)
            ))
            return self.driver.find_element_by_css_selector(css_selector)
        self.wait_for_element_by_css_selector = wait_for_element_by_css_selector


    def tearDown(self):
        super(IntegrationTests, self).tearDown()
        time.sleep(5)
        print('Terminating')
        self.server_process.terminate()
        time.sleep(5)
        print((self.server_process))
        print((self.server_process.is_alive()))
        self.driver.quit()

    def startServer(self, app):
        def run():
            app.scripts.config.serve_locally = True
            app.run_server(
                port=8050,
                debug=False,
                processes=2
            )

        # Run on a separate process so that it doesn't block
        print('Running')
        self.server_process = multiprocessing.Process(target=run)
        self.server_process.start()
        time.sleep(15)

        # Visit the dash page
        try:
            self.driver.get('http://localhost:8050{}'.format(
                app.config['routes_pathname_prefix'])
            )
        except:
            print('Failed attempt to load page, trying again')
            print(self.server_process)
            print(self.server_process.is_alive())
            time.sleep(5)
            print(requests.get('http://localhost:8050'))
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

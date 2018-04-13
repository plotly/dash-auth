## Dash Authorization and Login

Docs: [https://plot.ly/dash/authentication](https://plot.ly/dash/authentication)

License: MIT

Tests: [![CircleCI](https://circleci.com/gh/plotly/dash-auth.svg?style=svg)](https://circleci.com/gh/plotly/dash-auth)

For local testing, install and use tox:

```
TOX_PYTHON_27=python2.7 TOX_PYTHON_36=python3.6 tox
```

Or create a virtualenv, install the dev requirements, and run individual
tests or test classes:

```
virtualenv venv
source venv/activate
pip install -r dev-requirements.txt
python -m unittest -v tests.test_plotlyauth.ProtectedViewsTest
```

Note that Python 2.7.7 or greater is required.

## Dash Authorization and Login

Docs: [https://dash.plotly.com/authentication](https://dash.plotly.com/authentication)

License: MIT

Tests: [![CircleCI](https://circleci.com/gh/plotly/dash-auth.svg?style=svg)](https://circleci.com/gh/plotly/dash-auth)

For local testing, install and use tox:

```
TOX_PYTHON_27=python2.7 TOX_PYTHON_36=python3.6 tox
```

Or create a virtualenv, install the dev requirements, and run individual
tests or test classes:

```
python -m venv venv
. venv/bin/activate
pip install -r dev-requirements.txt
python -k ba001
```

Note that Python 3.6 or greater is required.

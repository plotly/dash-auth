# Contributing

## Publishing

This package is available on PyPI. We can create a new version as often as whenever a PR is merged.

To publish:
1. **PyPI Access**
- Ask @chriddyp to be added as a maintainer on PyPI.
Note that for security reasons, this is restricted to Plotly employees.
- PyPI has a new website, register your account here: https://pypi.org/.
- If you already have a PyPI account, you'll need to make sure that your email is registered
- Add your PyPI credentials to a file at `~/.pypirc`.
It will look something like:
```
[distutils]
index-servers =
   pypi
[pypi]
username:your_pypi_username
password:your_pypi_password
```

2. **Changelogs and Version**
- Check the recent commits and PRs and add anything notable to the `CHANGELOG.md` file
- Bump the version number in `dash_auth/version.py`. Follow [Semantic Versioning 2.0.0](https://semver.org/)
- Create a PR and tag @chriddyp for review
- Once reviewed, merge into master.

3. **Create a Python Build**
```
$ rm -rf dist build
$ python setup.py sdist bdist_wheel
```

4. **Upload the Build to PyPI**
First, install twine: the new tool for uploading packages to PyPI
```
$ pip install twine
```

Then, upload to PyPI using Twine.
```
$ twine upload dist/dash_auth-VERSION.tar.gz
```
Where `VERSION` refers to the version number of package. This file was created in Step 4.

5. **Git Tag**
Create a Git Tag with the version number:
```
git tag -a 'v0.1.0' -m 'v0.1.0'
git push origin master --follow-tags
```

6. **Test it out**
In a new folder, make sure the installation uploaded correctly.
Note that sometimes PyPI's servers take a few minutes for installations to be recognized.
```
pip install dash-auth --upgrade
```

7. **Update the version number in `dopsa`**
We fix the version number in [`dash-on-premise-sample-app`](https://github.com/plotly/dash-on-premise-sample-app/).

Create a PR to update that version in https://github.com/plotly/dash-on-premise-sample-app/blob/master/requirements.txt.

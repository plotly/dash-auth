# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [1.0.2] - 2018-05-31
### Fixed
- Use update_or_create for OAuth app creation when available, to avoid
  race condition.

## [1.0.1] - 2018-05-02
### Fixed
- Handle the case where more than one OAuth app exists in streambed.

## [1.0.0] - 2018-04-11
### Added
- `PlotlyAuth` now supports "secret" authentication using the `share_key`
parameter.

### Changed
- All `Auth` subclasses must now implement `index_auth_wrapper()`. See
`basic_auth.py` for an example that preserves the existing behaviour.

## [0.1.0] - 2018-03-27
### Added
- `PlotlyAuth` now supports multiple URLs. Supply a localhost URL and a remote
URL in order to test your Plotly login on your local machine while keeping
the login screen available in your deployed app. Usage:
```
dash_auth.PlotlyAuth(app, 'my-app', 'private', [
    'https://my-deployed-dash-app.com',
    'http://localhost:8050'
])
```
See https://github.com/plotly/dash-auth/pull/29

### Fixed
- `PlotlyAuth` is now stateless. This allows `PlotlyAuth` to be
used in Dash Apps that are deployed with multiple workers.
See https://github.com/plotly/dash-auth/pull/32

## [0.0.11] - 2018-02-01
### Added
- Added logging on request failure for the `PlotlyAuth` handler
- Added retry logic for the `PlotlyAuth` handler

## [0.0.10] - 2017-10-05
### Fixed
- The oauth redirect URL is now trailing-backslash insensitive

## [0.0.9] - 2017-10-02
### Fixed
- Allow the version to be imported with `dash_auth.__version__`

## [0.0.8] - 2017-09-26
### Fixed
- Wrap string responses in a `flask.Response` so that cookies can be added to it

## [0.0.7] - 2017-09-19
### Fixed
- Fixed authentication with path based routing with dash==0.18.3
### Added
- Add path and secure attributes to the plotly auth cookies for `PlotlyAuth`
### Removed
- No longer implicitly saves `localhost:8050` as a valid oauth redirect URL for `PlotlyAuth`

## [0.0.6] - 2017-09-05
### Fixed
- Path-based routing with Plotly auth for apps where `app.config.requests_pathname_prefix` is not `/` now works

## [0.0.5] - 2017-08-22
### Added
- Python 3 support for Basic Auth

## [0.0.4] - 2017-08-17
### Added
- Integration and continuous integration tests
- Python 3 support for Plotly Auth

## [0.0.4rc7] - 2017-08-09
First stable Python 2 release

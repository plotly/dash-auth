# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [1.3.2] - 2018-12-18
### Change
Changed basic-auth to use a dictionary of valid credentials, rather than lists.
This ensures only one valid password per user, and credential checks are faster.

## [1.3.1] - 2018-12-05
### Changed
Changed the deprecation notice to only 2 repos (`dash-basic-auth` and `dash-enterprise-auth`).
The oauth abstraction can still be used with dash-auth.

## [1.3.0] - 2018-12-04

Add integrations with Dash Deployment Server 2.6. [#75](https://github.com/plotly/dash-auth/pull/75)
This version works on both 2.5 and 2.6.

dash-auth will be split into 2 repositories:

- `dash-basic-auth` -> basic_auth
- `dash-enterprise-auth` -> Dash Deployment Server integration, replace PlotlyAuth.

### Added
- Pending deprecation notice for PlotlyAuth.

### Changed
- Logout button changed to a `dcc.LogoutButton` if app is on Dash Deployment Server 2.6 
- `get_username` from request headers if app is on Dash Deployment Server 2.6
- Disabled authentication if app is on Dash Deployment Server>=2.6, authentication is now performed on the Dash Deployment Server for all deployed apps.

### Fixed
- Fixed logout invalidation url and put in a try/catch so the token is still cleared from the cookies after an error.

## [1.2.0] - 2018-10-11
### Fixed
- Kerberos tickets can be retrieved from a Dash Deployment Server and used
to perform multi-hop authentication. [#64](https://github.com/plotly/dash-auth/pull/64)

## [1.1.4] - 2018-09-11
### Fixed
- Token invalidation from self signed on-prem. [#56](https://github.com/plotly/dash-auth/pull/56)
- Logout button redirect to app url. [#56](https://github.com/plotly/dash-auth/pull/56)
- Cookie clear use `requests_pathname_prefix`. [#56](https://github.com/plotly/dash-auth/pull/56)

## [1.1.3] - 2018-09-12
### Fixed
- Detect requests coming from orca pdf generation and disable unsupported secure cookies. [#60](https://github.com/plotly/dash-auth/pull/60)

## [1.1.2] - 2018-08-15
### Fixed
- Remove trailing slash from the cookie path.

## [1.1.1] - 2018-08-14
### Fixed
- Cookies path take `requests_pathname_prefix` instead of `routes`. [#54](https://github.com/plotly/dash-auth/pull/54)
- Ensure failed cookie unsign clear the cookies.

## [1.1.0] - 2018-08-10
### Added
- Added `get_username` to `PlotlyAuth`, signed cookie stored in `USERNAME_COOKIE`.
- Added `get_user_data` to `PlotlyAuth`, custom cookie that can contains any json data for the user.
- Added `logout` to `PlotlyAuth`, helper method to remove the auth cookies and invalidate the token.
- Added `create_logout_button` which create a dash logout button that will logout on click to be inserted in the layout.

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

# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [0.0.10] - 2017-10-05
### Fixed
- The oauth redirect URL is no longer trailing-backslash insensitive

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

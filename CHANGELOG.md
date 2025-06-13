# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed
- daemon logging now works as intended (was hidded due to interference with dependency logging settings)
- `ReadoutCounts` works as intended for multiple frame collections

### Changed
- property methods are written dynamically
- `processing_method` is not longer available; mean processing is always used
- channel name `img` -> `mean`

### Added
- yaq properties for selected parameters
- initial release

# Changelog

All notable changes to this project are documented here.

This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-06-06

### Changed

- Simplified the README install and quick-start instructions for PyPI.
- Clarified the primary launch form as `codex-bridge-python base_url api_key model`.
- Clarified the optional fourth positional argument name as `context_size`.

## [0.1.0] - 2026-06-06

### Added

- Initial PyPI-ready release as `codex-bridge-python`.
- Console entry point: `codex-bridge-python`.
- Python API package: `codex_bridge`.
- Responses API to Chat Completions proxy for Codex CLI.
- Simplified launcher with persisted Codex config in `~/.codex-bridge-python`.
- Model catalog generation and upstream `/v1/models` normalization.
- Release documentation and GitHub Actions workflow for PyPI Trusted Publishing.

# Changelog

## Unreleased — v0.2.0 development

- Refactored the original monolithic script into an installable Python CLI with separate naming, metadata, movie, TV and filesystem modules.
- Replaced independent preview and apply paths with a virtual filesystem and an exact, reusable operation plan.
- Added operation journals and conservative rollback of confirmed changes.
- Hardened path validation, collision handling and TMDB error reporting.
- Added synthetic-media regression tests, a reproducible demo, architecture documentation and multi-platform automated checks.
- Retained the original command entry point for compatibility and the first script as a historical reference.

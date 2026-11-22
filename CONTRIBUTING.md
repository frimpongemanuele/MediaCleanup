# Contributing

MediaCleanup is a small, safety-first Python project. Improvements to filename handling, test coverage, reliability and documentation are welcome.

## Development workflow

1. Create a local branch from the current default branch.
2. Install the package in a Python 3.10+ virtual environment with `python -m pip install .`.
3. Make focused changes with regression tests where behavior changes.
4. Run `python -m unittest discover -v`.
5. Run the synthetic demo from the README and verify the package still builds with `python -m pip wheel --no-deps --wheel-dir dist .`.

Please use synthetic fixtures instead of personal libraries and mock metadata calls. Do not add keys, real media, private paths, plan files or operation journals to commits.

## Reporting issues

Include a minimal synthetic example, the Python version and operating system, the expected behavior and the actual behavior. Redact all credentials and private filenames from logs. If a report concerns a security issue or potential data loss, follow [SECURITY.md](SECURITY.md) instead of posting sensitive details publicly.

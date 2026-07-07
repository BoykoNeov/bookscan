"""Shared pytest config for server tests.

Mirrors pipeline/tests/conftest.py's marker registrations so this directory
is self-contained when run standalone (``pytest server/tests``) and not just
when collected as part of a repo-root run that happens to also load
pipeline/tests/conftest.py first.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: real-data test that loads GPU models / runs Tesseract against a "
        "real testset image; skipped if those deps are unavailable. Deselect "
        "with -m 'not slow'.",
    )

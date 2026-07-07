"""Shared pytest config for pipeline tests."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end browser test (Playwright + Chromium); skipped if the "
        "browser is unavailable. Deselect with -m 'not e2e'.",
    )
    config.addinivalue_line(
        "markers",
        "slow: real-data test that loads GPU models / runs Tesseract against a "
        "real testset image; skipped if those deps are unavailable. Deselect "
        "with -m 'not slow'.",
    )

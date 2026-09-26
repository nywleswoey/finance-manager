"""conftest's `_restore_settings`: an assignment to `settings` ends with its test.

The two tests run in file order. The first leaves the gate open the way the old dev-bypass
fixtures did; the second is the auth test that used to run after them and inherit it.
"""
from portfolio.config import settings

_BEFORE = {}


def test_a_fixture_opens_the_gate():
    _BEFORE.update(settings.__dict__)
    settings.dev_auth_bypass = not _BEFORE["dev_auth_bypass"]
    settings.cron_secret = "leaked"


def test_the_next_test_does_not_inherit_it():
    assert settings.__dict__ == _BEFORE

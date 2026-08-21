import importlib.util
from unittest.mock import patch

import pytest

from config import Settings
from errors import IntegrationNotConfigured


def test_extension_secret_has_no_default_and_is_required_at_call_time():
    settings = Settings(_env_file=None)

    with pytest.raises(IntegrationNotConfigured):
        settings.require_chat_extension_secret()


def test_authenticator_rejects_missing_and_uses_constant_time_comparison():
    assert importlib.util.find_spec("manager.order_chat_auth") is not None
    from manager.order_chat_auth import OperatorChatAuthenticator

    authenticator = OperatorChatAuthenticator("x" * 32)

    assert authenticator.matches(None) is False
    with patch(
        "manager.order_chat_auth.compare_digest", return_value=True
    ) as compare:
        assert authenticator.matches("candidate") is True
    compare.assert_called_once_with("candidate", "x" * 32)

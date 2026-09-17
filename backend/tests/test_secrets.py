"""
integrations/secrets.py — the fix for the real plaintext-secret-storage
bug found in this task's Phase 0 audit (generic /api/integrations
config was stored and returned unencrypted). Every new secret path
must go through encrypt_config_secrets()/redact_config(); these tests
lock that contract in.
"""
from integrations import secrets


def test_encrypt_decrypt_roundtrip():
    encrypted = secrets.encrypt_secret("sk_test_abc123")
    assert encrypted != "sk_test_abc123"
    assert secrets.decrypt_secret(encrypted) == "sk_test_abc123"


def test_decrypt_invalid_token_returns_none():
    assert secrets.decrypt_secret("not-a-real-token") is None


def test_encrypt_config_secrets_only_touches_known_secret_fields():
    config = {"api_key": "sk_live_xyz", "model": "gpt-4o", "base_url": "https://api.example.com"}
    encrypted = secrets.encrypt_config_secrets(config)
    assert encrypted["api_key"] != "sk_live_xyz"
    assert encrypted["model"] == "gpt-4o"
    assert encrypted["base_url"] == "https://api.example.com"


def test_redact_config_never_returns_the_secret_value():
    config = {"api_key": "sk_live_xyz", "model": "gpt-4o"}
    redacted = secrets.redact_config(config)
    assert "api_key" not in redacted
    assert redacted["has_api_key"] is True
    assert redacted["model"] == "gpt-4o"
    assert "sk_live_xyz" not in str(redacted)


def test_redact_config_false_flag_when_secret_empty():
    redacted = secrets.redact_config({"api_key": ""})
    assert redacted["has_api_key"] is False


def test_redact_error_text_strips_bearer_and_sk_keys():
    text = "Request failed: Authorization: Bearer abcDEF123456789012345678 with key sk_live_ABCDEF123456"
    scrubbed = secrets.redact_error_text(text)
    assert "abcDEF123456789012345678" not in scrubbed
    assert "sk_live_ABCDEF123456" not in scrubbed


def test_redact_error_text_strips_query_secrets():
    text = "GET https://api.example.com/thing?api_key=supersecretvalue123&id=42"
    scrubbed = secrets.redact_error_text(text)
    assert "supersecretvalue123" not in scrubbed


def test_encrypt_decrypt_config_roundtrip():
    config = {"api_key": "sk_live_roundtrip", "model": "gpt-4o"}
    encrypted = secrets.encrypt_config_secrets(config)
    decrypted = secrets.decrypt_config_secrets(encrypted)
    assert decrypted["api_key"] == "sk_live_roundtrip"
    assert decrypted["model"] == "gpt-4o"

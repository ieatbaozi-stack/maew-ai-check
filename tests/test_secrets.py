from __future__ import annotations

import sys

from maew.secrets import SecretStore


def test_dpapi_secret_store_roundtrip(tmp_path):
    store = SecretStore(tmp_path)
    secret_val = "maew-test-secret-payload-12345"
    store.set("claude_cookie", secret_val)

    raw_bytes = (tmp_path / "secrets.dat").read_bytes()
    if sys.platform == "win32":
        # Encrypted with DPAPI: plaintext must NEVER appear on disk!
        assert b"maew-test-secret-payload-12345" not in raw_bytes

    assert store.get("claude_cookie") == secret_val

    store.set("claude_cookie", None)
    assert store.get("claude_cookie") is None

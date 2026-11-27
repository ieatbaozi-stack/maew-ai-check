"""Windows DPAPI encrypted secret storage (zero external crypto dependencies).

Stores secrets in ``%APPDATA%/maew-ai-check/secrets.dat`` encrypted with
Windows ``CryptProtectData`` bound to the current Windows user account.
Refuses to write plaintext on non-Windows hosts unless explicitly opted in
for tests via ``MAEW_ALLOW_PLAINTEXT_SECRETS=1``.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("maew.secrets")

_SECRETS_FILENAME = "secrets.dat"
_ALLOW_PLAINTEXT_ENV = "MAEW_ALLOW_PLAINTEXT_SECRETS"
_ENTROPY = b"maew-ai-check::dpapi::v1"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wt.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


if sys.platform == "win32":
    _CRYPT32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _CRYPT32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wt.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _CRYPT32.CryptProtectData.restype = wt.BOOL

    _CRYPT32.CryptUnprotectData.argtypes = _CRYPT32.CryptProtectData.argtypes
    _CRYPT32.CryptUnprotectData.restype = wt.BOOL

    _KERNEL32.LocalFree.argtypes = [ctypes.c_void_p]
    _KERNEL32.LocalFree.restype = ctypes.c_void_p


def _to_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_byte]]:
    buf = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    blob = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    return blob, buf


def _from_blob(blob: _DataBlob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _KERNEL32.LocalFree(blob.pbData)


def dpapi_protect(plaintext: bytes) -> bytes:
    in_blob, _in_buf = _to_blob(plaintext)
    entropy_blob, _ent_buf = _to_blob(_ENTROPY)
    out_blob = _DataBlob()
    ok = _CRYPT32.CryptProtectData(
        ctypes.byref(in_blob),
        "maew-ai-check",
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    return _from_blob(out_blob)


def dpapi_unprotect(ciphertext: bytes) -> bytes:
    in_blob, _in_buf = _to_blob(ciphertext)
    entropy_blob, _ent_buf = _to_blob(_ENTROPY)
    out_blob = _DataBlob()
    ok = _CRYPT32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    return _from_blob(out_blob)


class SecretStore:
    def __init__(self, base_dir: Path):
        self._path = base_dir / _SECRETS_FILENAME

    def _load_all(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_bytes()
            if not raw:
                return {}
            if sys.platform == "win32":
                text = dpapi_unprotect(raw).decode("utf-8")
            else:
                text = raw.decode("utf-8")
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            log.warning("Failed to decrypt secrets store; treating as empty")
            return {}

    def _save_all(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data).encode("utf-8")
        if sys.platform == "win32":
            self._path.write_bytes(dpapi_protect(payload))
            return
        if os.environ.get(_ALLOW_PLAINTEXT_ENV) == "1":
            self._path.write_bytes(payload)
            return
        raise RuntimeError(
            "Refusing to write plaintext secrets off Windows without "
            f"{_ALLOW_PLAINTEXT_ENV}=1."
        )

    def get(self, key: str) -> str | None:
        return self._load_all().get(key)

    def set(self, key: str, value: str | None) -> None:
        data = self._load_all()
        if value:
            data[key] = value
        else:
            data.pop(key, None)
        self._save_all(data)

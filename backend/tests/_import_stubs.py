"""Minimal stand-ins for optional third-party SDKs so ``import server`` works
in a bare dev venv. CI installs requirements.txt, where every real module
exists and nothing here is used (each stub is only installed when the
real import fails).

Stubs only satisfy import-time attribute lookups; anything that would
actually call Google / Microsoft / PyJWT raises.
"""
from __future__ import annotations

import importlib
import sys
import types


def _missing(name: str) -> bool:
    try:
        importlib.import_module(name)
        return False
    except Exception:  # noqa: BLE001
        return True


def _module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    parent, _, child = name.rpartition(".")
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], child, mod)
    return mod


class _Unavailable:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("stubbed SDK — not available in this test environment")


def install() -> None:
    if _missing("jwt"):
        class InvalidTokenError(Exception):
            pass

        class ExpiredSignatureError(InvalidTokenError):
            pass

        def _fail(*_a, **_k):
            raise InvalidTokenError("stubbed PyJWT")

        _module(
            "jwt",
            PyJWKClient=_Unavailable,
            InvalidTokenError=InvalidTokenError,
            ExpiredSignatureError=ExpiredSignatureError,
            get_unverified_header=_fail,
            decode=_fail,
        )
    if _missing("msal"):
        _module("msal", ConfidentialClientApplication=_Unavailable)
    if _missing("google.auth.transport.requests"):
        for name in ("google", "google.auth", "google.auth.transport", "google.oauth2"):
            if name not in sys.modules:
                _module(name)
        _module("google.auth.transport.requests", Request=_Unavailable)
        _module("google.oauth2.credentials", Credentials=_Unavailable)
    if _missing("google_auth_oauthlib.flow"):
        _module("google_auth_oauthlib")
        _module("google_auth_oauthlib.flow", Flow=_Unavailable)
    if _missing("googleapiclient.discovery"):
        class HttpError(Exception):
            pass

        _module("googleapiclient")
        _module("googleapiclient.discovery", build=_Unavailable)
        _module("googleapiclient.errors", HttpError=HttpError)

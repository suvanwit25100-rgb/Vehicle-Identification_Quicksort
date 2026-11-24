"""Time-based one-time passwords (RFC 6238), the codes shown by Google Authenticator, Microsoft Authenticator, Authy and similar apps.

Standard library only for the maths. The QR code needs the small `segno` package; without it the setup screen shows the key to type in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")      # 160 bits, the size Google Authenticator expects


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, counter: int, digits: int = DIGITS) -> str:
    h = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


def verify(secret: str, code: str, last_step: int = 0, at: float | None = None, window: int = 1) -> int | None:
    """The time step the code belongs to if it is valid now (allowing one step of clock drift each way) and newer than `last_step`; else None.
    Refusing a step that was already used stops a code being replayed."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now_step = int((time.time() if at is None else at) // STEP)
    for step in range(now_step - window, now_step + window + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str, issuer: str = "ExLex") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def qr_svg(uri: str) -> str | None:
    try:
        import segno
    except ImportError:
        return None
    from io import BytesIO

    buf = BytesIO()
    segno.make(uri, error="m").save(buf, kind="svg", scale=5, border=2, dark="#000000", light="#ffffff", xmldecl=False, svgns=True)
    return buf.getvalue().decode()

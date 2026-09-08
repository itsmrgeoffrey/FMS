"""Multi-factor authentication (TOTP) — INACTIVE SCAFFOLD.

Nothing in this module runs. It is a complete, reviewed implementation left
commented out so that MFA is a deliberate decision with a known cost, rather
than an unexamined gap. FMS currently authenticates with a password (or the
configured directory/LDAP bind) and no second factor; that boundary is stated
plainly here instead of being discovered later.

WHY IT IS NOT ENABLED
    Turning MFA on is not a backend change alone. It changes the login contract
    (a successful password check stops being a successful login), so every
    client, the directory-auth path, and account recovery all have to change
    together. Half-enabling it is worse than not having it: an enrolment screen
    that cannot be enforced gives the appearance of a second factor without one.

WHAT THIS GIVES YOU
    RFC 6238 TOTP, 30-second step, 6 digits, SHA-1 — the format Google
    Authenticator, Authy, 1Password and Microsoft Authenticator all speak.
    Verification uses only the standard library; no new runtime dependency.
    Generating the QR *image* needs `qrcode` (or render the otpauth:// URI in
    the browser, which avoids the dependency entirely).

TO ENABLE — the full checklist, in order
    1. models.User: add
           mfa_secret: Mapped[str | None]        = mapped_column(String(64), nullable=True)
           mfa_enabled: Mapped[bool]             = mapped_column(Boolean, default=False)
           mfa_recovery_hashes: Mapped[str|None] = mapped_column(Text, nullable=True)  # JSON list
    2. database._ADDED_COLUMNS["users"]: add the same three columns, so existing
       SQLite databases are retrofitted on startup (create_all never alters an
       existing table — see the comment above _ADDED_COLUMNS).
    3. Uncomment this module.
    4. auth_routes.login: when user.mfa_enabled, do NOT issue a token on a valid
       password. Return {"mfa_required": True, "mfa_token": <short-lived>} and
       add POST /auth/mfa/verify that exchanges mfa_token + code for the real
       token. The interim token must be separately signed, single-use and
       ~5 minutes, so it can never be used as a session token.
    5. Add POST /auth/mfa/enrol (returns secret + provisioning URI + recovery
       codes) and POST /auth/mfa/confirm (verifies one code before setting
       mfa_enabled — never enable on enrolment alone, or a user can lock
       themselves out of their own account).
    6. Audit every transition: MFA_ENROLLED, MFA_ENABLED, MFA_DISABLED,
       MFA_FAILED, MFA_RECOVERY_USED. Add the first four to
       audit.SECURITY_ACTIONS so they appear in Security Events.
    7. Admin reset path: an admin must be able to clear MFA for a locked-out
       user, and that action must itself be dual-controlled (see
       services/dual_control.py) — it is a way to bypass a second factor.
    8. Frontend: enrolment UI in Administration › My Account, a code prompt in
       the login flow, and recovery-code download at enrolment time.
    9. Directory/LDAP users: decide explicitly whether MFA is enforced locally
       or delegated to the directory. Do not leave this implicit.

SECURITY NOTES THAT ARE EASY TO GET WRONG
    · Rate-limit verification (the existing _rate_limited in auth_routes covers
      login; MFA verify needs its own bucket) — 6 digits is 1e6, brute-forceable
      in minutes without a limit.
    · Compare codes with hmac.compare_digest, never ==.
    · Store recovery codes hashed, exactly like passwords. Show them once.
    · Accept a ±1 step drift, no more. A wider window multiplies the guess space.
    · A used code should not be replayable within its window — track the last
      accepted step per user if you need strict single-use.

"""

# ─────────────────────────────────────────────────────────────────────────────
# import base64
# import hashlib
# import hmac
# import json
# import secrets
# import struct
# import time
# from urllib.parse import quote
#
# DIGITS = 6
# STEP_SECONDS = 30
# DRIFT_STEPS = 1          # accept the neighbouring step each side (±30s)
# RECOVERY_CODE_COUNT = 10
#
#
# def generate_secret() -> str:
#     """A fresh base32 TOTP secret (160 bits, the RFC 4226 recommendation)."""
#     return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
#
#
# def provisioning_uri(secret: str, username: str, issuer: str = "FMS") -> str:
#     """otpauth:// URI for an authenticator app. Render as a QR code, or show
#     the secret for manual entry. Nothing here needs a QR library."""
#     label = quote(f"{issuer}:{username}")
#     return (
#         f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
#         f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
#     )
#
#
# def _code_for_step(secret: str, step: int) -> str:
#     """RFC 6238 TOTP for one time step."""
#     key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
#     digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
#     offset = digest[-1] & 0x0F
#     code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
#     return str(code % (10 ** DIGITS)).zfill(DIGITS)
#
#
# def verify_code(secret: str, code: str, at: float | None = None) -> bool:
#     """True if `code` is valid now, allowing DRIFT_STEPS of clock skew.
#     Constant-time compare — a timing oracle here leaks the expected code."""
#     if not secret or not code or not code.strip().isdigit():
#         return False
#     supplied = code.strip()
#     step = int((at if at is not None else time.time()) // STEP_SECONDS)
#     for delta in range(-DRIFT_STEPS, DRIFT_STEPS + 1):
#         if hmac.compare_digest(_code_for_step(secret, step + delta), supplied):
#             return True
#     return False
#
#
# def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
#     """Single-use codes for a lost authenticator. Show once, store only hashes."""
#     return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}"
#             for _ in range(count)]
#
#
# def hash_recovery_codes(codes: list[str]) -> str:
#     """JSON list of hashes, for User.mfa_recovery_hashes. Reuses the app's
#     password hasher so the work factor stays consistent."""
#     from backend.auth import hash_password
#     return json.dumps([hash_password(c) for c in codes])
#
#
# def consume_recovery_code(stored_json: str | None, supplied: str) -> tuple[bool, str | None]:
#     """Check a recovery code and burn it. Returns (accepted, updated_json).
#     The caller must persist updated_json — a recovery code that survives use
#     is just a second password."""
#     from backend.auth import verify_password
#     if not stored_json:
#         return False, stored_json
#     hashes = json.loads(stored_json)
#     for i, h in enumerate(hashes):
#         if verify_password(supplied.strip(), h):
#             remaining = hashes[:i] + hashes[i + 1:]
#             return True, json.dumps(remaining)
#     return False, stored_json
# ─────────────────────────────────────────────────────────────────────────────

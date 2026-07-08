"""Unit tests for the security-critical auth + RBAC logic (no DB, no network)."""
import time

from backend import auth
from backend.models import User


def _user(role="admin", uid="u1", username="alice"):
    return User(id=uid, username=username, role=role)


# ─── Password hashing ────────────────────────────────────────────────────────

def test_hash_and_verify_password():
    h = auth.hash_password("supersecret1")
    assert h != "supersecret1"                 # never stored in plain text
    assert h.startswith("pbkdf2_sha256$")
    assert auth.verify_password("supersecret1", h)


def test_verify_rejects_wrong_password():
    h = auth.hash_password("supersecret1")
    assert not auth.verify_password("supersecret2", h)
    assert not auth.verify_password("", h)


def test_verify_rejects_garbage_hash():
    assert not auth.verify_password("x", "not-a-valid-hash")


def test_two_hashes_of_same_password_differ():
    # Random per-password salt.
    assert auth.hash_password("same") != auth.hash_password("same")


# ─── Signed tokens ───────────────────────────────────────────────────────────

def test_token_roundtrip_carries_identity():
    tok = auth.create_token(_user(role="analyst", uid="u9", username="bob"))
    payload = auth._verify_token(tok)
    assert payload is not None
    assert payload["uid"] == "u9"
    assert payload["username"] == "bob"
    assert payload["role"] == "analyst"


def test_tampered_token_is_rejected():
    tok = auth.create_token(_user())
    body, sig = tok.split(".")
    # Flip a character in the payload — signature no longer matches.
    tampered = body[:-1] + ("A" if body[-1] != "A" else "B") + "." + sig
    assert auth._verify_token(tampered) is None


def test_wrong_signature_is_rejected():
    tok = auth.create_token(_user())
    body, _ = tok.split(".")
    assert auth._verify_token(f"{body}.deadbeef") is None


def test_expired_token_is_rejected(monkeypatch):
    tok = auth.create_token(_user())          # exp set with the real clock
    future = time.time() + 100 * 3600         # jump past the TTL
    monkeypatch.setattr(auth.time, "time", lambda: future)
    assert auth._verify_token(tok) is None


def test_malformed_token_is_rejected():
    assert auth._verify_token("garbage") is None
    assert auth._verify_token("") is None


# ─── RBAC capability model ───────────────────────────────────────────────────

def test_role_capabilities_matrix():
    assert auth.role_has("admin", "admin")
    assert auth.role_has("admin", "act")
    assert auth.role_has("admin", "view")

    assert not auth.role_has("analyst", "admin")
    assert auth.role_has("analyst", "act")
    assert auth.role_has("analyst", "view")

    assert not auth.role_has("viewer", "admin")
    assert not auth.role_has("viewer", "act")
    assert auth.role_has("viewer", "view")


def test_unknown_role_has_no_capabilities():
    assert not auth.role_has("superuser", "view")
    assert not auth.role_has("", "act")


def test_valid_roles_set():
    assert auth.VALID_ROLES == {"admin", "analyst", "viewer"}

"""Unit tests for OFAC sanctions screening (backend/services/sanctions.py).

Runs against the bundled sample list — no network, no full OFAC download needed.
The sample list is pinned explicitly so these tests behave identically whether
or not a downloaded data/ofac_sdn.json is present on the machine.
"""
from pathlib import Path

from backend.services import sanctions as S

_ORIG_FULL_LIST = S._FULL_LIST


def setup_module():
    # Force the bundled sample list even if the full OFAC download exists.
    S._FULL_LIST = Path("__nonexistent_for_tests__")
    S.reload()


def teardown_module():
    S._FULL_LIST = _ORIG_FULL_LIST
    S.reload()


# ─── Matching ────────────────────────────────────────────────────────────────

def test_exact_name_matches():
    m = S.screen("GLOBAL SHADOW TRADING LLC")
    assert m is not None
    assert m.matched_name == "GLOBAL SHADOW TRADING LLC"
    assert m.score == 1.0


def test_match_is_case_insensitive():
    m = S.screen("global shadow trading llc")
    assert m is not None and m.score == 1.0


def test_corporate_suffix_noise_ignored():
    # "LTD" vs "LLC" and missing suffix entirely should still match exactly
    assert S.screen("Global Shadow Trading") is not None
    assert S.screen("GLOBAL SHADOW TRADING LTD") is not None


def test_punctuation_normalized():
    m = S.screen("Ivan-Petrov, Volkov")
    assert m is not None
    assert m.matched_name == "IVAN PETROV VOLKOV"


def test_token_order_insensitive():
    m = S.screen("VOLKOV IVAN PETROV")
    assert m is not None
    assert m.matched_name == "IVAN PETROV VOLKOV"


# ─── Non-matches (false-positive control) ────────────────────────────────────

def test_ordinary_name_does_not_match():
    assert S.screen("John Smith") is None
    assert S.screen("Acme Plumbing Supplies") is None


def test_partially_similar_name_below_threshold_does_not_match():
    # Shares one token ("TRADING") with a listed entity — must not hit at 0.90
    assert S.screen("Sunrise Trading Partners") is None


def test_empty_and_none_do_not_match():
    assert S.screen(None) is None
    assert S.screen("") is None
    assert S.screen("   ") is None


# ─── Match metadata ──────────────────────────────────────────────────────────

def test_match_carries_program_and_source():
    m = S.screen("REDLINE SHIPPING CO")
    assert m is not None
    assert m.program == "IRAN"
    assert "OFAC" in m.source


def test_reload_returns_entry_count():
    assert S.reload() >= 8


# ─── PEP list support ────────────────────────────────────────────────────────

def test_pep_list_loaded_and_tagged(monkeypatch):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        pep_file = Path(td) / "pep.json"
        pep_file.write_text(
            '[{"name": "SENATOR JAMES EXAMPLE", "type": "Individual", "program": "", "source": "Test PEP"}]'
        )
        monkeypatch.setattr(S, "_PEP_LIST", pep_file)
        S.reload()
        try:
            m = S.screen("Senator James Example")
            assert m is not None
            assert m.list_type == "PEP"
            # SDN entries still match and keep their type
            sdn = S.screen("REDLINE SHIPPING CO")
            assert sdn is not None and sdn.list_type == "SDN"
        finally:
            monkeypatch.undo()
            S.reload()


# ─── Fail-closed behaviour ───────────────────────────────────────────────────
# Screening produces the most serious output FMS can emit (an OFAC block/reject
# obligation). A list that failed to load must NEVER be reported as "no match",
# because the caller cannot tell that apart from a genuinely clean transaction.

import json
import tempfile
from pathlib import Path

import pytest


def test_corrupt_list_raises_instead_of_returning_no_match(monkeypatch):
    """A truncated/corrupt list must raise, not silently screen everything clean."""
    with tempfile.TemporaryDirectory() as td:
        broken = Path(td) / "ofac_sdn.json"
        broken.write_text('[{"name": "GLOBAL SHADOW TRA')   # truncated JSON
        monkeypatch.setattr(S, "_FULL_LIST", broken)
        S.reload()
        try:
            with pytest.raises(S.ScreeningUnavailable):
                S.screen("ANYONE AT ALL")
            st = S.status()
            assert st["ok"] is False
            assert st["state"] == "error"
        finally:
            monkeypatch.undo()
            S.reload()


def test_implausibly_small_list_is_treated_as_corrupt(monkeypatch):
    """A 200-OK error page parses to ~0 rows. That is a broken file, not a short list."""
    with tempfile.TemporaryDirectory() as td:
        tiny = Path(td) / "ofac_sdn.json"
        tiny.write_text(json.dumps([{"name": "ONLY ONE ENTRY"}]))
        monkeypatch.setattr(S, "_FULL_LIST", tiny)
        S.reload()
        try:
            with pytest.raises(S.ScreeningUnavailable):
                S.screen("ONLY ONE ENTRY")
            assert S.status()["state"] == "error"
        finally:
            monkeypatch.undo()
            S.reload()


def test_sample_fallback_still_screens_but_reports_degraded(monkeypatch):
    """No downloaded list: screening still works, but must not claim to be healthy."""
    monkeypatch.setattr(S, "_FULL_LIST", Path("__nonexistent__"))
    S.reload()
    try:
        assert S.screen("GLOBAL SHADOW TRADING LLC") is not None   # still screening
        st = S.status()
        assert st["state"] == "sample"
        assert st["ok"] is False                                   # but not healthy
    finally:
        monkeypatch.undo()
        S.reload()


def test_refresh_refuses_to_overwrite_good_list_with_error_page(monkeypatch):
    """The failure that silently disables screening: a maintenance page returning 200."""
    calls = {"wrote": False}

    class _Resp:
        content = b"<html>Service temporarily unavailable</html>"
        def raise_for_status(self):
            return self

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)

    orig_write = Path.write_text
    def _guard(self, *a, **k):
        calls["wrote"] = True
        return orig_write(self, *a, **k)
    monkeypatch.setattr(Path, "write_text", _guard)

    try:
        with pytest.raises(RuntimeError, match="refusing to overwrite"):
            S.refresh_from_treasury()
        assert calls["wrote"] is False, "must not touch the existing list on a bad download"
    finally:
        monkeypatch.undo()

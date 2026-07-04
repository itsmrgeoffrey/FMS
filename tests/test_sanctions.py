"""Unit tests for OFAC sanctions screening (backend/services/sanctions.py).

Runs against the bundled sample list — no network, no full OFAC download needed.
"""
from backend.services import sanctions as S


def setup_module():
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

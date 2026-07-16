"""Unit tests for the compliance features added in the regulatory-gap build:
evaluate() core, rule snapshot/backtest plumbing, sanctions list breadth and
severity, 314(a) parsing, draft batch XML, and the National Priorities map.
No DB, no network — run from the project root:  python -m pytest
"""
import asyncio
from datetime import datetime

from backend.adapters.base import NormalizedTransaction
from backend.models import FraudCase
from backend.routers.insights import NATIONAL_PRIORITIES, _parse_314a_subjects
from backend.routers.reports import _xml_batch
from backend.services import analyzer as A
from backend.services import sanctions as S

BASE = datetime(2026, 6, 1, 12, 0, 0)


def txn(**kw) -> NormalizedTransaction:
    defaults = dict(
        id="t1", account_id="acc-1", amount=1_000.0, direction="OUTWARD",
        timestamp=BASE, counterparty_account="cp-1", counterparty_name="Known Vendor",
        channel="online", currency="USD", reference=None, status="completed",
        source_table="outward", batch_id=None,
    )
    defaults.update(kw)
    return NormalizedTransaction(**defaults)


# ─── evaluate(): the shared deterministic core ────────────────────────────────

def test_evaluate_benign_txn_not_flagged():
    v = A.evaluate(txn(amount=900.0), [])
    assert v["is_fraudulent"] is False
    assert v["ctr"].required is False


def test_evaluate_structuring_band_flagged_and_sar():
    # 9,500 sits in the 90%-of-threshold structuring band — a hard signal,
    # SAR-reportable at any amount.
    v = A.evaluate(txn(amount=9_500.0), [])
    assert v["is_fraudulent"] is True
    assert "near_threshold_amount" in v["risk"].components
    assert v["sar_recommended"] is True


def test_evaluate_ctr_at_threshold():
    v = A.evaluate(txn(amount=10_000.0), [])
    assert v["ctr"].required is True
    assert v["ctr"].trigger == "SINGLE_TXN"


# ─── snapshot / restore / override round-trip (backtest plumbing) ─────────────

def test_snapshot_restore_roundtrip_changes_verdict_only_inside_window():
    snap = A.snapshot_rules()
    baseline = A.evaluate(txn(amount=8_500.0), [])  # below the default 90% band
    assert "near_threshold_amount" not in baseline["risk"].components

    try:
        # Widen the structuring band to 80% — 8,500 now falls inside it.
        A.apply_rule_overrides({"structuring_band_ratio": 0.80})
        widened = A.evaluate(txn(amount=8_500.0), [])
        assert "near_threshold_amount" in widened["risk"].components
    finally:
        A.restore_rules(snap)

    after = A.evaluate(txn(amount=8_500.0), [])
    assert "near_threshold_amount" not in after["risk"].components
    assert A.snapshot_rules() == snap


# ─── Sanctions: severity tie-break and list breadth ──────────────────────────

def _inject_entries(entries):
    S._entries = [
        {**e, "norm": S._normalize(e["name"])}
        for e in entries
    ]
    S._build_indexes()


def _reset_entries():
    S._entries = None  # next screen() lazily reloads the real files
    S._exact = {}
    S._trigram_index = {}
    S._trigrams_per_entry = []
    S._screen_cache.clear()


def test_sdn_wins_tie_against_pep():
    try:
        _inject_entries([
            {"name": "Jane Q Launderer", "program": "", "type": "", "source": "PEP list", "list_type": "PEP"},
            {"name": "Jane Q Launderer", "program": "SDGT", "type": "individual", "source": "OFAC SDN", "list_type": "SDN"},
        ])
        m = S.screen("Jane Q Launderer")
        assert m is not None and m.list_type == "SDN"
    finally:
        _reset_entries()


def test_non_sdn_match_is_review_not_block():
    async def run():
        try:
            _inject_entries([
                {"name": "Sectoral Bank OJSC", "program": "UKRAINE-EO13662",
                 "type": "entity", "source": "OFAC Consolidated (non-SDN)", "list_type": "NON_SDN"},
            ])
            result = await A.analyze(txn(counterparty_name="Sectoral Bank OJSC"), [])
            assert result.is_fraudulent is True
            assert result.fraud_type == "watch-list match"
            assert result.sanctions_hit is False          # SDN block banner reserved for SDN
            assert "WATCH-LIST MATCH" in result.reasons[0]
        finally:
            _reset_entries()
    asyncio.run(run())


def test_parse_ofac_csv_primary_and_alias():
    prim = '1234,"ACME EVIL CORP","entity","SDGT",\n5678,"-0-","x","y",\n'
    alt = '1234,1,"aka","ACME WICKED LLC",\n'
    entries = S._parse_ofac_csv(prim, alt, "OFAC Consolidated (non-SDN)")
    names = {e["name"] for e in entries}
    assert names == {"ACME EVIL CORP", "ACME WICKED LLC"}
    assert all(e["program"] == "SDGT" for e in entries)
    assert {e["source"] for e in entries} == {"OFAC Consolidated (non-SDN)", "OFAC Consolidated (non-SDN) (alias)"}


# ─── 314(a) subject-file parsing ──────────────────────────────────────────────

def test_314a_parse_business_and_person_columns():
    csv_text = (
        "Tracking,Last Name,First Name,Middle Name,Business Name\n"
        "T1,Smith,John,Q,\n"
        "T2,,,,Acme Front Company LLC\n"
    )
    subjects = _parse_314a_subjects(csv_text)
    assert subjects == ["John Q Smith", "Acme Front Company LLC"]


def test_314a_parse_headerless_takes_first_cell():
    subjects = _parse_314a_subjects("Jane Doe,x\nJohn Roe,y\n")
    assert subjects == ["Jane Doe", "John Roe"]


# ─── Draft batch XML ──────────────────────────────────────────────────────────

def _case(**kw) -> FraudCase:
    c = FraudCase()
    defaults = dict(
        id="case-1", account_id="acc-1", amount=12_500.0, currency="USD",
        direction="OUTWARD", counterparty_name="Acme Vendor",
        counterparty_account="cp-9", channel="wire", timestamp=BASE,
        created_at=BASE, ctr_reason="Single transaction exceeds threshold",
        fraud_type="structuring", reasons=["r1", "r2"], ai_summary="summary text",
    )
    defaults.update(kw)
    for k, v in defaults.items():
        setattr(c, k, v)
    return c


def test_ctr_xml_draft_structure():
    xml = _xml_batch([_case()], "ctr").decode("utf-8")
    assert "<FormTypeCode>CTRX</FormTypeCode>" in xml
    assert "DRAFT" in xml and "FMS-COMPLETION-REQUIRED" in xml
    assert "<TotalCashOutAmountText>12500.00</TotalCashOutAmountText>" in xml
    assert "Acme Vendor" in xml


def test_sar_xml_draft_has_narrative_and_deadline():
    xml = _xml_batch([_case()], "sar").decode("utf-8")
    assert "<FormTypeCode>SARX</FormTypeCode>" in xml
    assert "officer must review" in xml
    assert "FMS 30-day clock" in xml
    assert "<SuspiciousActivityTypeID>32</SuspiciousActivityTypeID>" in xml  # structuring


# ─── National Priorities map ──────────────────────────────────────────────────

def test_national_priorities_complete_and_honest():
    assert len(NATIONAL_PRIORITIES) == 8
    assert {p["coverage"] for p in NATIONAL_PRIORITIES} <= {"direct", "partial", "screening"}
    fraud = next(p for p in NATIONAL_PRIORITIES if p["priority"] == "Fraud")
    assert fraud["coverage"] == "direct"
    # A transaction monitor must not claim direct coverage of predicate crimes
    # it can only see the money-movement mechanics of.
    tco = next(p for p in NATIONAL_PRIORITIES if "Transnational" in p["priority"])
    assert tco["coverage"] == "partial"

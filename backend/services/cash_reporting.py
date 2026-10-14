"""Cash reporting groups use explicit IDs; account behavior stays independent."""
from datetime import date
from decimal import Decimal


def cash_groups(txn, history, business_day):
    items = {}
    for item in [*history, txn]:
        if (item.is_cash is True and item.currency == txn.currency
                and item.direction == txn.direction and business_day(item) == business_day(txn)
                and item.timestamp <= txn.timestamp):
            items[(item.source_table, item.id)] = item
    rows = list(items.values())
    keys = [("account", txn.account_id)]
    if txn.account_holder_id:
        keys.append(("account_holder", txn.account_holder_id))
    if txn.conductor_id:
        keys.append(("conductor", txn.conductor_id))
    fields = {"account": "account_id", "account_holder": "account_holder_id", "conductor": "conductor_id"}
    return [{"basis": basis, "subject_id": value,
        "items": [item for item in rows if getattr(item, fields[basis]) == value]}
        for basis, value in keys]


def matching_exemption(txn, records, business_day):
    candidates = [record for record in records if record["subject_id"] == txn.account_holder_id
        and txn.account_id in record["account_ids"]]
    if not candidates:
        return None, "NO_RECORD"
    today = date.fromisoformat(business_day(txn))
    for record in candidates:
        if record["status"] != "ACTIVE" or not record.get("approved_by"):
            continue
        if not (date.fromisoformat(record["effective_from"]) <= today
                <= min(date.fromisoformat(record["expires_on"]), date.fromisoformat(record["review_due"]))):
            continue
        if txn.acting_as_agent is not False:
            continue
        if record["exemption_type"] == "PAYROLL_CUSTOMER" and not (
                txn.direction == "OUTWARD" and txn.cash_purpose == "PAYROLL"):
            continue
        return record, "APPLIED"
    return None, "REVIEW_REQUIRED"


def assess_cash(txn, history, records, business_day):
    current_record, exemption_status = matching_exemption(txn, records, business_day)
    groups = cash_groups(txn, history, business_day)
    summaries = []
    for group in groups:
        assessed = [(item, *matching_exemption(item, records, business_day)) for item in group["items"]]
        reportable = [item for item, record, status in assessed if record is None]
        summaries.append({"basis": group["basis"], "subject_id": group["subject_id"],
            "gross_total": str(sum((item.amount for item in group["items"]), Decimal(0))),
            "reportable_total": str(sum((item.amount for item in reportable), Decimal(0))),
            "transaction_count": len(group["items"]),
            "transactions": [{"source": item.source_table, "transaction_id": item.id,
                "account_id": item.account_id, "amount": str(item.amount), "reportable": record is None,
                "exemption_status": status, "exemption_id": record["id"] if record else None,
                "approved_by": record["approved_by"] if record else None} for item, record, status in assessed]})
    triggered = [group for group in summaries if Decimal(group["reportable_total"]) > Decimal("10000")]
    return {"candidate": bool(triggered), "business_date": business_day(txn),
        "threshold": "10000", "direction": txn.direction, "groups": summaries,
        "exemption": {"status": exemption_status, "id": current_record["id"] if current_record else None,
            "approved_by": current_record["approved_by"] if current_record else None},
        "triggered_group": max(triggered, key=lambda group: Decimal(group["reportable_total"])) if triggered else None}

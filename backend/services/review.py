from sqlalchemy import or_, and_
from backend.models import FraudCase

OPEN_STATUSES = ("OPEN", "UNDER_REVIEW", "ESCALATED", "PENDING_APPROVAL")


def legacy_obligation():
    return and_(FraudCase.status == "CLEAN", or_(FraudCase.ctr_required == True,
        FraudCase.sar_recommended == True, FraudCase.sanctions_hit == True))


def open_condition():
    return or_(FraudCase.status.in_(OPEN_STATUSES), legacy_obligation())


def queue_condition(queue: str):
    if queue == "approvals":
        return FraudCase.status == "PENDING_APPROVAL"
    if queue == "escalations":
        return and_(FraudCase.review_level == "SENIOR", FraudCase.status.in_(("ESCALATED", "UNDER_REVIEW")))
    if queue == "review":
        return or_(
            and_(FraudCase.review_level == "STANDARD", FraudCase.status.in_(("OPEN", "UNDER_REVIEW"))),
            legacy_obligation(),
        )
    return open_condition()


def flagged_condition():
    return or_(FraudCase.status != "CLEAN", legacy_obligation())

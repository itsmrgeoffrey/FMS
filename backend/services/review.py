from sqlalchemy import or_, and_
from backend.models import FraudCase

OPEN_STATUSES = ("OPEN", "UNDER_REVIEW", "ESCALATED")


def legacy_obligation():
    return and_(FraudCase.status == "CLEAN", or_(FraudCase.ctr_required == True,
        FraudCase.sar_recommended == True, FraudCase.sanctions_hit == True))


def open_condition():
    return or_(FraudCase.status.in_(OPEN_STATUSES), legacy_obligation())


def flagged_condition():
    return or_(FraudCase.status != "CLEAN", legacy_obligation())

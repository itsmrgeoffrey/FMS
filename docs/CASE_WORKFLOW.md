# Case Review and Approval

FMS separates investigation from final approval using named accounts. In Settings > Users, assign `analyst` to inputters and `approver` to checkers. Administrators also have checker access. Use accounts belonging to separate people; FMS enforces different usernames, not independent human identities.

## Queues and States

| Queue | States | Responsible role |
|---|---|---|
| Review queue | OPEN, standard UNDER_REVIEW, legacy CLEAN with outstanding obligations | Analyst |
| Decision approvals | PENDING_APPROVAL | Approver or Admin, excluding the proposal maker |
| Escalations | ESCALATED, senior UNDER_REVIEW | Approver or Admin |
| All open | All outstanding workflow states | Viewable by all roles |

Start review claims a case and persists `assigned_to`, `assigned_at`, `review_level`, and `review_due_at`. The current follow-up date is one day after claiming or rejection; it is an internal review target, not a statutory SAR filing deadline. Pre-upgrade unassigned reviews can be claimed. Existing escalated cases are routed to senior review at startup.

CONFIRMED and DISMISSED actions create pending proposals with a rationale. They do not close cases. Approval sets CONFIRMED_FRAUD or DISMISSED. Rejection returns UNDER_REVIEW to the original maker. Withdrawal resumes review under that maker. Escalation clears assignment and sets the senior review level. A senior reviewer submits proposals under the same independent-approval requirement.

CTR and SAR flags remain separate from case dispositions. Neither dismissal nor fraud confirmation establishes that a regulatory report was filed or removes an existing reporting flag.

## API Sequence

Use the signed session token for the relevant named user in the Authorization header.

1. Analyst: POST `/cases/{id}/actions` with `{"action":"REVIEW"}`.
2. Assigned analyst: POST the same endpoint with `{"action":"CONFIRMED","note":"Evidence and rationale"}` or action DISMISSED.
3. Independent checker: POST `/cases/{id}/decision/approve` with `{"note":"Independent review complete"}`; or `/decision/reject` with a nonblank rejection note.
4. Original maker may POST `/cases/{id}/decision/cancel` while pending.

Other actions are RELEASED, ESCALATED (analyst only, with reason), and NOTE_ADDED (with note). Authentication determines the actor; client-supplied actor fields do not authorize an action. Closed or pending cases reject ordinary review actions. The maker cannot approve their own proposal, even after changing roles.

## Bulk Work

POST `/cases/bulk-actions`:

```json
{
  "action": "CONFIRMED",
  "rationale": "Shared evidence supporting these proposed fraud decisions",
  "all_matching": true,
  "filters": {"queue": "review", "status": "UNDER_REVIEW", "direction": "INWARD"}
}
```

Alternatively, set `all_matching` to false and supply `case_ids`. Supported actions: REVIEW, RELEASED, ESCALATED, CONFIRMED, DISMISSED, APPROVE, REJECT. Selection is snapshotted when submitted, with a limit of 100,000 case IDs per job. Conditions and the requester's current active role are rechecked when each chunk runs; assigned-case and maker-checker restrictions still apply. Ineligible cases fail individually and appear in job counters and sampled errors.

The worker commits each 100-case chunk together with its progress. After interruption it resumes from committed progress. Server databases lock the job and cases during each chunk. The default SQLite deployment should retain the existing single-worker configuration. Poll GET `/cases/batches/{id}` for PENDING, RUNNING, COMPLETED or FAILED. Counts include processed, succeeded and failed; up to 100 failures are stored. This implementation limit is not evidence of a completed 50,000-case performance benchmark.

Tables: `fraud_cases` stores current workflow state and assignment; `case_decisions` stores proposals and checker decisions; `case_actions` stores per-case history; `case_batches` stores durable bulk jobs. New tables and additive columns are created at startup. Approval queues are in Alerts; protected configuration approvals remain administrator-only in Settings > Approvals.

"""Tell a submitter what became of their use case — but only after an architect has seen it.

FR-12: "route every rejection or integration finding to an architect through Teams Approvals BEFORE
the submitter is notified." A workload cannot guarantee that on its own — it ends AT the question,
and what happens next is a human's decision on a different day. So the ordering is made structural:
this service consumes `approvals:decisions`, and the architect's decision is the EVENT that
releases the submitter's message. There is no path where the message goes first, because there is
no code that could send it before the decision exists.

Why here and not in the workload. CLAUDE.md's stated exception to gateway-only egress is SUBSTRATE
egress to a fixed configured URL, carrying ids, counts and links and never model content —
`meeting_notifier` is the precedent and this is the second thing so added. A workload posting
outward would be a third path with different rules.

**What it will not say.** A rejection reaching a submitter carries the outcome, the tracking
reference and a link — never the architect's comment and never the reasoning. OA-1 wants an
architect to see every rejection; it does not want their private assessment forwarded. And CR-16
(output classification does not exceed audience clearance) is the reason a summary is not simply
passed through: the submitter is a different audience from the reviewer.

`USECASE_WEBHOOK_URL` unset means it logs what it WOULD post, which is how to watch it before
wiring a destination.
"""
from __future__ import annotations

import sys
from typing import Any

from lab.platform import config, redis_client, streams
from lab.platform.contracts import (
    APPROVAL_FINAL,
    USE_CASE_DESIGN,
    USE_CASE_SCREENING,
    ApprovalStatus,
    Decision,
)
from lab.platform.webhook import post_json
from lab.substrate import approvals

SERVICE = "usecase-notifier"
GROUP = "usecase-notifier"

#: The processes whose decisions concern a submitter. An approval raised by anything else — a
#: meeting's speaker question, a Visio import — is acked and ignored: this service announces the
#: outcome of a USE CASE, and a channel that announced everything would bury the few that matter.
PROCESSES = (USE_CASE_SCREENING.name, USE_CASE_DESIGN.name)

#: What a submitter is told, per decision. Deliberately small and deliberately not the architect's
#: words: an outcome, not an assessment.
DECISIONS = frozenset(d.value for d in Decision)

#: An `update` is "changes requested" and still OPEN as an approval, but it IS an answer
#: the submitter needs — it is what returns the use case to them for more information.
_SETTLED = frozenset({*APPROVAL_FINAL, ApprovalStatus.UPDATE})

OUTCOMES = {
    Decision.APPROVE: "accepted",
    Decision.DECLINE: "not proceeding",
    Decision.UPDATE: "returned for changes",
}


def payload(request: dict, fields: dict) -> dict:
    """The message. Ids, an outcome and a link — never the reasoning, and never model content.

    The reviewer's comment is deliberately absent. OA-1 requires an architect to SEE every
    rejection; it does not require their private assessment to be forwarded to the person whose
    submission it was."""
    return {
        "request_id": request.get("request_id", ""),
        "subject": request.get("subject", ""),
        "outcome": OUTCOMES.get(Decision(fields["decision"]), str(fields["decision"])),
        "decided_at": fields.get("decided_at", ""),
        "submitter": request.get("requester", ""),
        "review_app": approvals.trace_url(request.get("trace_id", "")) or "",
    }


def _concerns_a_submission(request: dict) -> bool:
    """Only a use-case approval, and only one that named who submitted it.

    Matched on the process the ASKER declared, never on the subject line. Sniffing a subject seems
    harmless until it is not: "use_case" reduced to "case" matches "usecase meeting recording", and
    the failure is a meeting's speaker question posted to a business submitter.

    A request with no requester has nobody to tell — skipped explicitly rather than posting to an
    empty address."""
    if not request.get("requester"):
        return False
    payload = request.get("payload") or {}
    return payload.get("process", "") in PROCESSES


def handle(fields: dict, *, client=None) -> bool:
    """One decision. Returns whether a message was sent — False for the many that concern nobody."""
    request_id = fields.get("request_id", "")
    request = approvals.status(request_id, client=client) or {}
    if fields.get("decision") not in DECISIONS:
        return False
    if str(request.get("status")) not in _SETTLED:
        return False                                    # still open; nothing settled to announce
    if not _concerns_a_submission(request):
        return False

    said = payload(request, fields)
    if not config.USECASE_WEBHOOK_URL:
        print(f"{SERVICE}: would post {said}", flush=True)
        return True
    post_json(config.USECASE_WEBHOOK_URL, said)
    print(f"{SERVICE}: told {said['submitter']} that {request_id} is {said['outcome']}", flush=True)
    return True


def main() -> None:
    """One consumer of `approvals:decisions`, for the life of the process.

    A FAILED send leaves the entry unacked so the reclaim brings it back: a webhook outage delays a
    submitter's message rather than dropping it. `streams.serve` supplies the guard, the signal
    handling and the crash hygiene every one of these daemons needs."""
    client = redis_client.client()
    approvals.ensure_decision_groups(client)
    streams.serve(
        name=SERVICE,
        ready=(f"{SERVICE} ready  group={GROUP} "
               f"{'webhook configured' if config.USECASE_WEBHOOK_URL else 'NO webhook '
                  '(USECASE_WEBHOOK_URL unset) — it will log instead'}"),
        read=lambda: approvals.decision_events(GROUP, block_ms=streams.BLOCK_MS, count=50,
                                               client=client),
        handle=lambda entry_id, fields: _deliver(entry_id, fields, client=client))


def _deliver(entry_id: str, fields: dict, *, client) -> None:
    """Announce one decision and ack it. An exception propagates to `streams.serve`, which logs and
    backs off WITHOUT acking — so nothing is lost to a webhook that was down."""
    handle(fields, client=client)
    approvals.ack_decision(GROUP, entry_id, client=client)


if __name__ == "__main__":                                    # pragma: no cover
    main()

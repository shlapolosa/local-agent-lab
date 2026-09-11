"""The lab's own delivery contexts — the ADAPTER behind `lab.core.delivery.DeliveryRepository` that knows
the lab's runs: a minutes run was filed under its MEETING, a use-case run under its USE CASE, a diagram
run under its SUBMISSION. Read from the request hashes the runs already write; nothing new is stored.
A work-item adapter (Azure DevOps) satisfies the same port later with kind `workitem`."""
from __future__ import annotations

from lab.core.collab.model import ContentHandle, HandleKind
from lab.core.delivery import DeliveryContext
from lab.platform import redis_client, workflows

MEETING_PROCESSES = ("meeting_to_transcript", "transcript_to_minutes")
USECASE_PROCESSES = ("use_case_screening", "use_case_design", "use_case_investment", "use_case_provisioning")


def from_run(state: dict) -> DeliveryContext | None:
    """The delivery context a finished run's artifacts were produced under, or None when the run
    carried nothing that names one. PURE: takes the decoded request hash (`workflows.status`)."""
    process = str(state.get("process") or "")
    inputs = state.get("inputs") or {}
    if not isinstance(inputs, dict):
        inputs = {}
    owner = str(inputs.get("owner") or inputs.get("submitter") or state.get("requester") or "")
    if process in MEETING_PROCESSES:
        rec = inputs.get("recording") or (state.get("meeting") or {}).get("recording") or ""
        if ContentHandle.is_handle(rec):
            h = ContentHandle.parse(rec)
            if h.kind is HandleKind.RECORDING:
                label = str((state.get("meeting") or {}).get("subject") or "")
                return DeliveryContext("meeting", h.scope, label=label, owner=owner, source="lab")
        # No recording (a continuation staged before the field existed, or a recording that belongs to no
        # meeting): the run itself is still the delivery container — the same fallback every process has.
        rid = str(state.get("request_id") or "")
        return DeliveryContext("submission", rid, owner=owner, source="lab") if rid else None
    if process in USECASE_PROCESSES:
        ident = str(state.get("usecase_id") or inputs.get("usecase_id") or "")
        if not ident and process == "use_case_screening":
            ident = str(state.get("request_id") or "")
        if ident:
            return DeliveryContext("usecase", ident, owner=owner, source="lab")
        rid = str(state.get("request_id") or "")
        return DeliveryContext("submission", rid, owner=owner, source="lab") if rid else None
    rid = str(state.get("request_id") or "")
    return DeliveryContext("submission", rid, owner=owner, source="lab") if rid else None


class LabDeliveryContexts:
    """`DeliveryRepository` over the lab's request hashes."""

    def __init__(self, client=None):
        self._client = client

    def _r(self):
        return self._client or redis_client.client()

    def context(self, key: str) -> DeliveryContext | None:
        ctx = DeliveryContext.parse(key, source="lab")
        if ctx.kind in ("submission", "usecase"):
            state = workflows.status(ctx.id, client=self._r())
            if not state:
                return None
            derived = from_run(state)
            return derived if derived and derived.key == key else DeliveryContext(ctx.kind, ctx.id, owner=str(state.get("requester") or ""), source="lab")
        if ctx.kind == "meeting":
            return ctx                      # the meeting is the provider's; the lab holds only its id
        return None                         # workitem: another adapter's kind


__all__ = ["from_run", "LabDeliveryContexts", "MEETING_PROCESSES", "USECASE_PROCESSES"]

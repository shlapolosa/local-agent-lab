"""Which identity each CAFÉ bounded context authenticates as.

Ten services, ten Entra app registrations, ten virtual keys — the docx pattern, one registration to
one key to one agent. The separation is not tidiness. Spend attributes per identity, so "the risk
officer costs four times what the cost engineer does" is a fact somebody can read rather than
infer; the gateway's per-tool ACL can differ per identity; and a wrong answer is attributable to
the bounded context that gave it rather than to "the use-case workload".

**But provisioning ten registrations is an operator action against a live tenant**, and this code
runs whether that has happened or not. A service with no credential of its own falls back to the
workload's shared one — the spend rolls up to the same team it rolled up to before, and the run
proceeds. What must NOT happen is a run failing because an identity somebody intended to create
does not exist yet, or worse, proceeding unauthenticated: the fallback is a different credential,
never no credential.

The parity test is what keeps the table honest: every service owning a step must appear here, so a
new CAFÉ service is caught at build time rather than by a spend ledger nobody reads.
"""
from __future__ import annotations

from lab.workloads.identity import agent_headers

__all__ = ["NoCredential", "PREFIX_FOR", "credential_for"]

#: Service -> environment prefix. `agent_headers` reads `<PREFIX>_CLIENT_ID`/`_CLIENT_SECRET` for
#: an Entra JWT, or `<PREFIX>_KEY` for the durable virtual key. Short stems, because they become
#: six environment variables each in a file a person has to read.
PREFIX_FOR: dict[str, str] = {
    "Business Analyst": "USECASE_BA",
    "Business Architect": "USECASE_BUSARCH",
    "Application Architect": "USECASE_APPARCH",
    "Risk Officer": "USECASE_RISK",
    "Product Owner": "USECASE_PO",
    "Data Architect": "USECASE_DATA",
    "Solution Architect": "USECASE_SOLARCH",
    "Technology Architect": "USECASE_TECHARCH",
    "Cost Engineer": "USECASE_COST",
    "Value Analyst": "USECASE_VALUE",
}


class NoCredential(RuntimeError):
    """Neither the service's own identity nor the workload's shared one is configured.

    Raised rather than returning an empty string, because an empty credential does not fail at the
    call — it fails at the gateway, as a 401 on some later tool, with nothing in the message to say
    that the cause was a missing environment variable in this process."""


def credential_for(service: str, *, fallback: str) -> str:
    """The bearer credential this bounded context calls the gateway with.

    Prefers the service's own registration; falls back to the workload's. The fallback is passed IN
    rather than read here, because the host is the composition root and this module reads no
    configuration of its own beyond the credential lookup `agent_headers` already owns."""
    prefix = PREFIX_FOR.get(service)
    if prefix:
        try:
            return agent_headers(prefix)["Authorization"].removeprefix("Bearer ").strip()
        except KeyError:
            pass                     # not provisioned yet — the shared identity, deliberately
    if not fallback:
        raise NoCredential(
            f"{service!r} has no credential and neither does the workload it runs in; set "
            f"{prefix or 'the service'}_KEY or the workload's own key before starting a run")
    return fallback

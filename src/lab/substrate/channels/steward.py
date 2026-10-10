"""The STEWARD's approval channel — the VOCABULARY queue (enabled when TEAMS_STEWARD_WEBHOOK_URL is
set; unset = disabled, and it says which setting by name, exactly as the other channels do).

WHY A SECOND CHANNEL. Approvals in this lab have two audiences with different tempos and, until now,
one queue. An OWNER is asked about THEIR artifact — urgent and personal, "your document, now"
(`association`, `draft-review`, `speaker-mapping`, `ea-import`, `impact-notice`). A STEWARD is asked
about the VOCABULARY — deliberate and periodic, "twenty terms when you have twenty minutes"
(`concept-admission`): widening or narrowing what every future document is classified against.
Measured on this lab's own stream 10 Oct 2026: **101 open concept-admission cards against ~37 of
everything else**, all of it on every channel. A steward opening Teams saw a wall of term questions;
an owner looking for their own card had to scroll past them. Neither audience was served.

The split is by approval KIND, declared once in `lab.platform.contracts` (`STEWARD_KINDS` /
`OWNER_KINDS`, a partition asserted by test, so a kind cannot be claimed by both queues or by
neither) and applied once in `approvals.channel_events(audience=...)`. That is TRIAGE, which is the
one thing `kind` is documented for — "channels triage by it; nothing dispatches on it". Nothing else
in the lab branches on an audience: the review app still sees the whole queue, because it is where
every channel's card sends a person to decide.

WHY A SUBCLASS. It is the Teams adapter aimed at a second Workflows webhook: the same Adaptive Card
envelope, the same shared `streams.serve` loop, the same leave-a-failed-send-unacked rule, the same
inbound `decide` binding through `approvals.human_decision`. Three class attributes are the whole
difference — its consumer group (`name`), its setting, and its audience — so anything learned about
the card or the loop is learned once, for both. A separate GROUP rather than a filter in front of
the Teams one, because a group is what makes the two feeds independently acked and independently
behind: a steward who has not looked for a week must not hold up an owner's card.

Run: .venv/bin/python -m lab.substrate.channels.steward   (loop; exits immediately if not configured)
"""
from lab.platform.contracts import ApprovalAudience
from lab.substrate.channels.teams import TeamsChannel


class StewardChannel(TeamsChannel):
    name = "steward"                                  # its own consumer group on approvals:requests
    setting = "TEAMS_STEWARD_WEBHOOK_URL"             # a DIFFERENT Teams channel's Workflows webhook
    audience = ApprovalAudience.STEWARD               # ... carrying only the vocabulary questions


if __name__ == "__main__":
    import sys
    StewardChannel().probe() if "--probe" in sys.argv[1:] else StewardChannel().run()

"""The ONTOLOGY queue — a steward's second job (enabled when TEAMS_ONTOLOGY_WEBHOOK_URL is set;
unset = disabled, and it says which setting by name, exactly as the other channels do).

WHY A THIRD CHANNEL. A vocabulary is a taxonomy plus the statements about how its concepts relate, and
a steward answers two different questions about it. "Should this term become a concept?" is a word and
a definition, twenty at a time. "How do these two concepts relate?" is read against a diagram or a
corpus, and a wrong answer puts an edge in the graph the DERIVED rung will reason over as if somebody
had drawn it. Different question, different rhythm, different evidence — and on one queue the twenty
terms bury the one relation, which is the measurement that split owner from steward in the first place
(101 concept-admission cards against ~37 of everything else, 10 Oct 2026).

The split is by approval KIND, declared once in `lab.platform.contracts` (`TAXONOMY_KINDS` /
`ONTOLOGY_KINDS` / `OWNER_KINDS`, a three-way partition asserted by test so a kind cannot be claimed
twice or by nobody) and applied once in `approvals.channel_events(audience=...)`.

WHY A SUBCLASS. It is the Teams adapter aimed at a third Workflows webhook: the same Adaptive Card
envelope, the same shared `streams.serve` loop, the same leave-a-failed-send-unacked rule, the same
inbound `decide` binding. Three class attributes are the whole difference, so anything learned about
the card or the loop is learned once, for all of them. A separate GROUP rather than a filter in front
of the taxonomy one, because a group is what makes the feeds independently acked and independently
behind: a steward who has not looked at relations for a week must not hold up the term queue.

Run: .venv/bin/python -m lab.substrate.channels.ontology   (loop; exits immediately if not configured)
"""
from lab.platform import config
from lab.platform.contracts import ApprovalAudience
from lab.substrate.channels.teams import TeamsChannel


class OntologyChannel(TeamsChannel):
    name = "ontology"                                 # its own consumer group on approvals:requests
    setting = "TEAMS_ONTOLOGY_WEBHOOK_URL"            # a THIRD Teams channel's Workflows webhook
    answers_on_card = config.TEAMS_ONTOLOGY_ANSWERS_ON_CARD
    audience = ApprovalAudience.ONTOLOGY              # ...carrying how the vocabulary's concepts RELATE
    #: The named stewards — the same people as the taxonomy queue, asked a different question. Unset =
    #: the queue goes to the room.
    recipients = config.FABRIC_STEWARDS


if __name__ == "__main__":
    import sys
    OntologyChannel().probe() if "--probe" in sys.argv[1:] else OntologyChannel().run()

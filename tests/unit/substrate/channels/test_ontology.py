"""lab.substrate.channels.ontology — the ONTOLOGY channel, OFFLINE.

The steward's OTHER queue: how the vocabulary's concepts RELATE, as against what it contains. Separated
from the taxonomy queue by APPROVAL KIND (see tests/unit/platform/test_contracts_approval_audience.py
for the three-way partition that decides which is which). Like its sibling it is the Teams adapter
aimed at another Workflows webhook — the same Adaptive Card envelope, its own consumer group, a feed
carrying only `ONTOLOGY_KINDS` — so three class attributes are the whole difference and anything
learned about the card or the loop is learned once, for all three.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/channels/test_ontology.py
"""
import io
from contextlib import redirect_stdout

from lab.platform import config
from lab.platform.contracts import ApprovalAudience
from lab.substrate import approvals
from lab.substrate.channels import ontology as O
from lab.substrate.channels import steward as S
from lab.substrate.channels import teams as T


def test_it_is_the_teams_adapter_with_its_own_queue_and_its_own_webhook():
    assert issubclass(O.OntologyChannel, T.TeamsChannel)
    assert O.OntologyChannel.name == "ontology"
    assert O.OntologyChannel.setting == "TEAMS_ONTOLOGY_WEBHOOK_URL"
    assert O.OntologyChannel.audience is ApprovalAudience.ONTOLOGY


def test_the_three_queues_are_three_groups_three_settings_and_three_audiences():
    """The property that makes them independent: a steward who has not looked at relations for a week
    must not hold up the term queue, and neither may hold up an owner's card."""
    channels = (T.TeamsChannel, S.StewardChannel, O.OntologyChannel)
    for attr in ("name", "setting", "audience"):
        values = [getattr(c, attr) for c in channels]
        assert len(set(values)) == 3, f"two channels share a {attr}: {values}"


def test_ontology_is_a_registered_approval_channel():
    """`approvals.CHANNELS` IS the set of consumer groups. One missing from it is a group
    `ensure_groups` never pre-creates and a queue `channel_lag` reports nothing about."""
    assert O.OntologyChannel.name in approvals.CHANNELS


def test_settings_default_to_its_own_config_value_not_another_queues():
    ch = O.OntologyChannel()
    assert ch.webhook == config.TEAMS_ONTOLOGY_WEBHOOK_URL
    # Two queues sharing one destination is the buried backlog the audience split exists to undo.
    assert ch.webhook != config.TEAMS_STEWARD_WEBHOOK_URL or not config.TEAMS_STEWARD_WEBHOOK_URL


def test_disabled_without_its_webhook_and_says_which_setting_by_name():
    """An unconfigured channel must not be a crash loop, and must not be silent either: a deploy that
    says nothing about a queue nobody reads is how an approval gate goes unattended."""
    ch = O.OntologyChannel("")
    assert not ch.enabled
    out = io.StringIO()
    with redirect_stdout(out):
        ch.run()
    assert "TEAMS_ONTOLOGY_WEBHOOK_URL" in out.getvalue()

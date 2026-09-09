"""Every agent this lab RUNS is one it publishes, and every agent it publishes is one it runs.

`contracts.AGENTS` is a declaration, and a declaration nothing checks is a wish. Three other places
already know which agents exist — the CAFE identity table, the step table that says which context owns
which step, and the provisioning scripts that mint the keys — and none of them could see the registry.
This is the two-way ratchet that makes them agree, in the shape
`test_contracts_match_servers.py` uses: two set differences, each with its own message, so a failure
says which direction drifted.

Why it matters more than tidiness: the card is what makes an agent's spend attributable to an AGENT
rather than to an opaque key. An agent running without a card spends invisibly; a card without an
agent advertises something nobody can call. Both are quiet.

Offline: imports only, no tenant, no gateway.
"""
import os
import sys

import pytest

from lab.platform.contracts import AGENTS, PROCESSES
from lab.workloads.usecase.identity import PREFIX_FOR
from lab.workloads.usecase.steps import STEPS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

BY_PREFIX = {a.prefix: a for a in AGENTS}


# ------------------------------------------------------------------ the CAFE ten
def test_every_cafe_identity_has_a_card_and_every_cafe_card_has_an_identity():
    """`PREFIX_FOR` is what the RUN authenticates as; `AGENTS` is what discovery advertises. This tier
    may not import a workload, so the registry cannot derive the table — which is exactly why it has
    to be checked."""
    declared = {a.prefix for a in AGENTS if a.prefix.startswith("USECASE_")} - {"USECASE_AGENT",
                                                                                "USECASE_DELIVERY"}
    running = set(PREFIX_FOR.values())
    assert running - declared == set(), "a CAFE context runs with no agent card — its spend is invisible"
    assert declared - running == set(), "an agent card names a CAFE context no step is owned by"


def test_each_cafe_card_claims_the_processes_its_steps_are_actually_owned_in():
    """The mapping is derived HERE from `steps.py` — the only place that really knows — and compared
    with what the card claims. A context that gains a design step and keeps a screening-only card
    would otherwise be advertised wrongly for as long as nobody looked."""
    process_of = {"use_case_screening": "use_case_screening", "use_case_design": "use_case_design"}
    from lab.workloads.usecase.steps import DESIGN_STEPS, SCREENING_STEPS
    owns: dict[str, set[str]] = {}
    for step in SCREENING_STEPS:
        owns.setdefault(step.service, set()).add(process_of["use_case_screening"])
    for step in DESIGN_STEPS:
        owns.setdefault(step.service, set()).add(process_of["use_case_design"])

    for service, processes in owns.items():
        spec = BY_PREFIX[PREFIX_FOR[service]]
        assert set(spec.processes) == processes, (
            f"{spec.name} claims {sorted(spec.processes)} but owns steps in {sorted(processes)}")


def test_every_step_is_owned_by_a_context_that_has_a_card():
    unknown = sorted({s.service for s in STEPS} - set(PREFIX_FOR))
    assert not unknown, f"steps owned by a service with no identity at all: {unknown}"


# ------------------------------------------------------------------ the provisioning scripts
def _provisioned_prefixes() -> set[str]:
    """Every env prefix a provisioning script actually mints a key for.

    Read from the scripts themselves rather than restated, for the reason `test_meeting_grants.py`
    reads its grant tables from `provision_meeting_agents`: a table copied into a test is a table that
    can drift from the thing it claims to describe.
    """
    import provision_usecase_agents as U
    found = set(U.SERVICE_PREFIXES.values())
    for module, names in (("provision_meeting_agents", ("MEETING_AGENT", "MINUTES_AGENT")),
                          ("provision_visio_agents", ("BA_AGENT", "ARCHITECT_AGENT"))):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts",
                                f"{module}.py"), encoding="utf-8").read()
        found |= {n for n in names if f"{n}_KEY" in src or f'"{n}' in src}
    found |= {"USECASE_AGENT", "USECASE_DELIVERY", "EA_AGENT"}   # the shared/workload identities
    return found


def test_every_provisioned_agent_has_a_card():
    missing = sorted(_provisioned_prefixes() - set(BY_PREFIX))
    assert not missing, f"these identities are provisioned but publish no card: {missing}"


def test_every_card_names_an_identity_something_provisions():
    extra = sorted(set(BY_PREFIX) - _provisioned_prefixes())
    assert not extra, f"these cards name an identity no script mints a key for: {extra}"


# ------------------------------------------------------------------ the cards themselves
@pytest.mark.parametrize("spec", AGENTS, ids=lambda s: s.name)
def test_a_card_is_publishable_as_declared(spec):
    """Rendered with no tenant, the way an unprovisioned deployment renders it."""
    card = spec.card("https://gw.example", "", "")
    assert card["name"] and card["description"] and card["skills"]
    assert all(s["id"] for s in card["skills"])
    unknown = sorted(set(spec.processes) - set(PROCESSES))
    assert not unknown, f"{spec.name} names unregistered processes {unknown}"


# ------------------------------------------------------------------ the gateway setting it needs
def test_the_gateway_loads_agents_back_out_of_its_own_store():
    """`store_model_in_db` is what makes a published card survive a restart, and nothing else says so.

    Root-caused in LiteLLM's source (proxy/proxy_server.py, v1.98.0): `_init_agents_in_db` — the
    DB -> in-memory registry load — is reachable only through `add_deployment`, which is scheduled
    and awaited only inside `if store_model_in_db is True`. The `is not True` branch carries an
    explicit exemption for MCP servers and agents were left out of it.

    Without the setting the failure is silent and delayed: publishing succeeds, the pane is right
    until the next deploy, and then it is empty for ever while the rows are still in Postgres and a
    republish fails on the `agent_name` unique constraint. Exactly the shape of defect this repo
    keeps meeting — correct at the moment somebody looked, wrong from then on — so it is asserted
    rather than remembered.
    """
    import yaml

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "config", "litellm-config.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    assert cfg["general_settings"].get("store_model_in_db") is True, (
        "general_settings.store_model_in_db must stay true, or the gateway writes agent cards to "
        "Postgres and never reads them back — the registry empties on the next restart")


def test_nothing_narrows_the_db_objects_the_gateway_loads():
    """`supported_db_objects`, when set, is an allowlist — and one that omits "agents" would undo the
    setting above while leaving it in place, which is worse than not having it."""
    import yaml

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, "config", "litellm-config.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    allowed = cfg["general_settings"].get("supported_db_objects")
    assert allowed is None or "agents" in allowed, (
        f"supported_db_objects={allowed} excludes agents, so they are never loaded from the store")

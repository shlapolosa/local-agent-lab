"""The deploy topology names the request stream and each workload's consumer group WITHOUT importing
the lab package (the CI deploy job does not install it). This is the parity check that keeps those
two literal declarations equal to what the workloads actually consume — drift either way would scale
a host on a stream or group nobody reads, which fails silently: the host never wakes."""
import importlib.util
import os

from lab.platform import workflows

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("lab_deploy_topology_gov", os.path.join(ROOT, "deploy", "topology.py"))
topology = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(topology)


def test_the_request_stream_is_the_one_workflows_publishes_to():
    assert topology.REQUEST_STREAM == workflows.REQ


def test_every_consumer_group_a_workload_is_scaled_on_is_a_registered_process_group():
    deployed = {topology.workload_group(s) for s in topology.WORKLOADS.values() if s.get("restart") == "ALWAYS"}
    assert deployed == set(workflows.GROUPS), "a process with no host, or a host scaled on no process"


def test_every_use_case_specialist_identity_reaches_the_workloads_that_call_it():
    """`credential_for` prefers a specialist's OWN identity and falls back to the workload's shared one
    when `<PREFIX>_KEY` is missing. The deploy allowlist admitted only USECASE_AGENT_*, so in the cloud
    every specialist key was stripped and all ten ran on the shared credential — silently, the one
    downgrade identity.py's own comment names as the thing that must not happen quietly."""
    from lab.workloads.usecase.identity import PREFIX_FOR

    for workload in ("usecase-screening", "usecase-design"):
        env = topology.env_for_role("workload", {f"{p}_KEY": "k" for p in PREFIX_FOR.values()}, workload=workload)
        missing = sorted(p for p in PREFIX_FOR.values() if f"{p}_KEY" not in env)
        assert not missing, f"{workload} would not receive: {missing}"


def test_every_stream_a_substrate_consumer_is_woken_on_is_one_it_reads():
    """A consumer scaled to zero wakes ONLY on the stream and group its scale rule names. Name the
    wrong one and it never wakes — a notification that silently never goes out."""
    from lab.platform import fabric_events
    from lab.substrate import approvals, continuations, fabric_projector, meeting_notifier, usecase_notifier

    reads = {
        "usecase-notifier": {(approvals.DEC, usecase_notifier.GROUP)},
        "continuations": {(approvals.DEC, continuations.GROUP)},
        "meeting-notifier": {(workflows.DONE, meeting_notifier.GROUP)},
        "fabric-projector": {(workflows.DONE, fabric_projector.GROUP)},
        "fabric-ingress": {(workflows.DONE, "fabric-ingress"), (fabric_events.STREAM, fabric_events.GROUP)},
    }
    woken = {n: set(s["wakes_on"]) for n, s in topology.SUBSTRATE.items() if s.get("wakes_on")}
    assert woken == reads, "a scaled-to-zero consumer must wake on exactly what it reads"

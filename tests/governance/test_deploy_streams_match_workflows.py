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

"""The quiet gate (deploy/gate.py): every deploy target asks the front door what is still running and
waits for it before restarting the gateway. Moved out of railway.py when Azure became the second target."""
import importlib.util
import io
import json
import os
import urllib.error

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("lab_deploy_gate", os.path.join(ROOT, "deploy", "gate.py"))
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _profile(**kw):
    return {"PUBLIC_GATEWAY_URL": "https://gw.example", "LITELLM_MASTER_KEY": "sk-master-fake", **kw}


def test_a_deploy_waits_for_runs_in_flight_and_proceeds_when_the_board_is_quiet(monkeypatch):
    """A restart under a run ends it with a 502 an hour of tokens in; the gate waits instead."""
    answers = iter([[{"process": "use_case_screening", "request_id": "wfr-1"}], [], []])
    slept = []
    monkeypatch.setattr(gate, "open_runs", lambda profile: next(answers))
    monkeypatch.setattr(gate.time, "sleep", lambda s: slept.append(s))
    assert gate.quiet_board(_profile(), wait_s=600) is True
    assert slept == [gate.QUIET_POLL_S]


def test_a_deploy_refuses_when_runs_are_still_in_flight_after_the_budget(monkeypatch, capsys):
    monkeypatch.setattr(gate, "open_runs", lambda profile: [{"process": "p", "request_id": "wfr-9"}])
    monkeypatch.setattr(gate.time, "sleep", lambda s: None)
    assert gate.quiet_board(_profile(), wait_s=60) is False
    assert "wfr-9" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        gate._require_quiet(_profile())
    assert e.value.code == 3


def test_force_skips_the_gate_and_an_unaskable_front_door_does_not_block_a_repair(monkeypatch):
    monkeypatch.setattr(gate, "open_runs", lambda profile: [{"process": "p", "request_id": "wfr-9"}])
    monkeypatch.setenv("LAB_DEPLOY_FORCE", "1")
    assert gate.quiet_board(_profile(), wait_s=0) is True
    monkeypatch.delenv("LAB_DEPLOY_FORCE")
    assert gate.quiet_board({"LITELLM_MASTER_KEY": "k"}, wait_s=0) is True      # no URL: cannot ask
    monkeypatch.setattr(gate, "open_runs", lambda profile: None)               # unreachable, for good
    monkeypatch.setattr(gate.time, "sleep", lambda s: None)
    assert gate.quiet_board(_profile(), wait_s=0) is True


def test_an_unreachable_front_door_is_waited_for_before_the_gate_gives_up_asking(monkeypatch):
    """Two rolls close together: the gateway is still restarting from the previous deploy, so the
    gate cannot ask — and used to proceed at once over a board it never saw. Now it waits out the
    restart; a run that is open when the door answers still holds the deploy."""
    answers = iter([None, None, [{"process": "p", "request_id": "wfr-5"}], []])
    slept = []
    monkeypatch.setattr(gate, "open_runs", lambda profile: next(answers))
    monkeypatch.setattr(gate.time, "sleep", lambda s: slept.append(s))
    assert gate.quiet_board(_profile(), wait_s=600) is True
    assert slept == [gate.QUIET_POLL_S] * 3, "two unreachable polls, one busy poll, then quiet"
    assert gate.QUIET_UNREACHABLE_WAIT_S >= 180, "a gateway restart takes minutes"


def test_open_runs_asks_the_front_door_with_the_master_key_and_says_when_it_cannot(monkeypatch, capsys):
    seen = {}
    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake(req, timeout=None):
        seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
        return R(json.dumps({"runs": [{"request_id": "wfr-2", "process": "p", "status": "running"}]}).encode())
    monkeypatch.setattr(gate.urllib.request, "urlopen", fake)
    assert gate.open_runs(_profile()) == [{"request_id": "wfr-2", "process": "p", "status": "running"}]
    assert seen == {"url": "https://gw.example/api/runs/open", "auth": "Bearer sk-master-fake"}
    def down(req, timeout=None):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(gate.urllib.request, "urlopen", down)
    assert gate.open_runs(_profile()) is None and "unreachable" in capsys.readouterr().err




def test_a_bearer_token_is_used_in_place_of_the_master_key(monkeypatch):
    seen = {}
    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake(req, timeout=None):
        seen["auth"] = req.get_header("Authorization")
        return R(json.dumps({"runs": []}).encode())
    monkeypatch.setattr(gate.urllib.request, "urlopen", fake)
    assert gate.open_runs({"PUBLIC_GATEWAY_URL": "https://gw", "GATE_BEARER": "eyJ.token.sig"}) == []
    assert seen["auth"] == "Bearer eyJ.token.sig"


def test_no_credential_proceeds_at_once_instead_of_waiting_for_a_door_it_could_never_open(monkeypatch, capsys):
    monkeypatch.setattr(gate.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("waited")))
    assert gate.quiet_board({"PUBLIC_GATEWAY_URL": "https://gw"}, wait_s=600) is True
    assert "no credential" in capsys.readouterr().out

"""Exercise the durable loop and real process/Planfile boundaries."""
import fcntl
import json
import sys
import time
from pathlib import Path

import pytest

from curllm_core.autonomy import Config, Monitor, run_command


def make_config(tmp_path, **extra):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    data = {"schema": "curllm.autonomy-config/v1", "repository": str(repo),
            "state_dir": str(tmp_path / "state"),
            "probes": [{"id": "browser", "argv": [sys.executable, "-c", "pass"],
                        "failure_threshold": 2, "recovery_threshold": 2}]}
    data.update(extra)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return Config(path)


def answer(ok):
    return {"ok": ok, "code": "passed" if ok else "exit_failed", "exit_code": 0 if ok else 1}


def sequence(*values):
    iterator = iter(values)
    return lambda *_: answer(next(iterator))


def with_repair(config, **extra):
    data = config.data
    data["probes"][0]["repair"] = {"argv": [sys.executable, "-c", "pass"],
                                   "authority_ref": "operator:local-fixture", **extra}
    config.path.write_text(json.dumps(data))
    return Config(config.path)


def test_failure_threshold_persists_and_deduplicates_ticket(tmp_path):
    cfg = make_config(tmp_path, planfile_project=str(tmp_path / "intake"))
    calls = []
    intake = lambda *args: calls.append(args[0]) or "P-1"
    assert Monitor(cfg, runner=sequence(False), intake=intake).cycle()["active_incidents"] == 0
    for _ in range(3):
        result = Monitor(cfg, runner=sequence(False), intake=intake).cycle()
        assert result["active_incidents"] == 1
    assert len(calls) == 1
    assert result["probes"][0]["handoff"] == "awaiting_controller"


def test_recovery_requires_consecutive_success_and_new_episode(tmp_path):
    cfg = make_config(tmp_path, planfile_project=str(tmp_path / "intake"))
    calls = []
    monitor = Monitor(cfg, runner=sequence(False, False, True, False, True, True, False, False),
                      intake=lambda *a: calls.append(a[0]) or f"P-{len(calls)}")
    summaries = [monitor.cycle() for _ in range(8)]
    assert [s["active_incidents"] for s in summaries] == [0, 1, 1, 1, 1, 0, 0, 1]
    assert len(set(calls)) == 2
    assert summaries[-1]["probes"][0]["episode"] == 2


def test_intake_outage_is_durable_and_retried_after_recovery(tmp_path):
    cfg = make_config(tmp_path, planfile_project=str(tmp_path / "intake"))
    def unavailable(*_):
        raise ConnectionError("private-secret-details")
    monitor = Monitor(cfg, runner=sequence(False, False), intake=unavailable)
    monitor.cycle()
    assert monitor.cycle()["probes"][0]["handoff"] == "outbox_pending"
    summary = Monitor(cfg, runner=sequence(True), intake=lambda *_: "P-1").cycle()
    assert summary["probes"][0]["ticket"] == "P-1"
    assert "private-secret-details" not in (cfg.state / "events.jsonl").read_text()


def test_repair_exit_zero_does_not_prove_effect(tmp_path):
    cfg = with_repair(make_config(tmp_path))
    monitor = Monitor(cfg, runner=sequence(False, False, True, False))
    monitor.cycle()
    result = monitor.cycle()
    assert result["active_incidents"] == 1
    assert result["probes"][0]["repair_state"] == "failed"
    assert not result["healthy"]


def test_verified_repair_records_observed_effect(tmp_path):
    cfg = with_repair(make_config(tmp_path))
    monitor = Monitor(cfg, runner=sequence(False, False, True, True))
    monitor.cycle()
    result = monitor.cycle()
    assert result["healthy"] and result["active_incidents"] == 0
    assert result["probes"][0]["repair_state"] == "verified"
    assert '"verb": "probe.verify"' in (cfg.state / "events.jsonl").read_text()


def test_recurrent_incident_does_not_reset_repair_budget(tmp_path):
    cfg = with_repair(make_config(tmp_path))
    monitor = Monitor(cfg, runner=sequence(False, False, True, True, False, False))
    summaries = [monitor.cycle() for _ in range(4)]
    assert summaries[-1]["probes"][0]["episode"] == 2
    assert summaries[-1]["probes"][0]["attempts"] == 1
    assert summaries[-1]["active_incidents"] == 1


def test_cooldown_and_attempt_budget(tmp_path):
    cfg = with_repair(make_config(tmp_path), max_attempts=2, cooldown_seconds=20)
    now = [100]
    calls = []
    def failed(spec, _):
        calls.append("repair" if "authority_ref" in spec else "probe")
        return answer(False)
    monitor = Monitor(cfg, runner=failed, clock=lambda: now[0])
    for _ in range(4):
        monitor.cycle()
    assert calls.count("repair") == 1
    now[0] += 21
    monitor.cycle()
    now[0] += 21
    monitor.cycle()
    assert calls.count("repair") == 2


def test_interrupted_repair_is_not_replayed(tmp_path):
    cfg = with_repair(make_config(tmp_path))
    def interrupted(spec, _):
        if "authority_ref" in spec:
            raise RuntimeError("process interrupted")
        return answer(False)
    monitor = Monitor(cfg, runner=interrupted)
    monitor.cycle()
    with pytest.raises(RuntimeError):
        monitor.cycle()
    calls = []
    resumed = Monitor(cfg, runner=lambda *a: calls.append(a[0]) or answer(False))
    assert resumed.cycle()["probes"][0]["repair_state"] == "unknown"
    assert len(calls) == 1


def test_no_repair_inferred_from_failed_probe_output(tmp_path):
    cfg = make_config(tmp_path)
    calls = []
    monitor = Monitor(cfg, runner=lambda *a: calls.append(a[0]) or answer(False))
    for _ in range(3):
        monitor.cycle()
    assert all("authority_ref" not in spec for spec in calls)


def test_changed_configuration_stops_before_repair(tmp_path):
    cfg = with_repair(make_config(tmp_path))
    calls = []
    def changed(spec, _):
        calls.append(spec)
        if len(calls) == 2:
            cfg.path.write_text(cfg.path.read_text() + "\n")
        return answer(False)
    monitor = Monitor(cfg, runner=changed)
    monitor.cycle()
    with pytest.raises(RuntimeError, match="changed"):
        monitor.cycle()
    assert len(calls) == 2


def test_concurrent_cycle_cannot_run_probe(tmp_path):
    cfg = make_config(tmp_path)
    cfg.state.mkdir()
    with (cfg.state / "cycle.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(RuntimeError, match="another"):
            Monitor(cfg, runner=lambda *_: pytest.fail("probe ran")).cycle()


@pytest.mark.parametrize("output", ['{"success":false}', '{"success":true,"errors":["bad"]}',
                                  '{"success":true,"failed":1}', '{"status":"ok"}', 'not json'])
def test_semantic_failure_with_zero_exit(output, tmp_path):
    spec = {"argv": [sys.executable, "-c", f"print({output!r})"], "oracle": "json"}
    result = run_command(spec, tmp_path)
    assert result["exit_code"] == 0 and result["code"] == "semantic_failed"


def test_real_json_probe_and_redacted_evidence(tmp_path):
    result = run_command({"argv": [sys.executable, "-c", 'print(\'{"success":true,"value":"private"}\')'],
                          "oracle": "json"}, tmp_path)
    assert result["ok"]
    assert "private" not in json.dumps(result)


def test_timeout_kills_descendants(tmp_path):
    marker = tmp_path / "marker"
    child = f"import time;from pathlib import Path;time.sleep(.4);Path({str(marker)!r}).touch()"
    parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(10)"
    result = run_command({"argv": [sys.executable, "-c", parent], "timeout_seconds": .15}, tmp_path)
    assert result["code"] == "timeout"
    time.sleep(.45)
    assert not marker.exists()


def test_real_fixture_repair_and_planfile_intake(tmp_path):
    pytest.importorskip("planfile")
    marker = tmp_path / "healthy"
    probe = {"id": "fixture", "argv": [sys.executable, "-c",
             f"from pathlib import Path;assert Path({str(marker)!r}).exists()"],
             "failure_threshold": 1,
             "repair": {"argv": [sys.executable, "-c", f"from pathlib import Path;Path({str(marker)!r}).touch()"],
                        "authority_ref": "operator:fixture"}}
    cfg = make_config(tmp_path, probes=[probe], planfile_project=str(tmp_path / "intake"))
    result = Monitor(cfg).cycle()
    assert result["healthy"] and result["probes"][0]["repair_state"] == "verified"
    from planfile import Planfile
    tickets = Planfile(str(tmp_path / "intake")).list_tickets()
    assert len(tickets) == 1
    assert tickets[0].status == "open"  # Monitoring recovery is not protected publication.


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(state_dir=d["repository"]),
    lambda d: d["probes"][0].update(argv="echo unsafe"),
    lambda d: d["probes"][0].update(timeout_seconds=301),
    lambda d: d["probes"][0].update(repair={"argv": [sys.executable, "-c", "pass"]}),
    lambda d: d["probes"].append(d["probes"][0].copy()),
])
def test_configuration_bounds(mutation, tmp_path):
    cfg = make_config(tmp_path)
    mutation(cfg.data)
    cfg.path.write_text(json.dumps(cfg.data))
    with pytest.raises(ValueError):
        Config(cfg.path)


def test_state_symlink_is_rejected(tmp_path):
    cfg = make_config(tmp_path)
    cfg.state.mkdir()
    foreign = tmp_path / "foreign"
    foreign.write_text("preserve")
    (cfg.state / "incidents.sqlite").symlink_to(foreign)
    with pytest.raises(ValueError, match="symlink"):
        Monitor(cfg).cycle()
    assert foreign.read_text() == "preserve"


def test_structured_cli_status(tmp_path, capsys):
    from curllm_core.cli.autonomy import main
    cfg = make_config(tmp_path)
    assert main(["cycle", "--config", str(cfg.path)]) == 0
    assert json.loads(capsys.readouterr().out)["healthy"]
    assert main(["status", "--config", str(cfg.path)]) == 0
    assert len(json.loads(capsys.readouterr().out)["incidents"]) == 1

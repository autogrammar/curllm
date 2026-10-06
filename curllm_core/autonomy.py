"""Bounded observation and verified repair; development authority stays external.

Only the operator's external configuration supplies commands. Probe output is
evidence, never executable instructions. Incidents and the Planfile outbox are
durable, serialized, and replayable; an interrupted repair is never replayed.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import resource
import signal
import sqlite3
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


SCHEMA = "curllm.autonomy-config/v1"
IDENTIFIER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}\Z")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plain_path(path: Path) -> Path:
    """Reject symlink components rather than resolving an authority boundary."""
    path = path.absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("symlinked configuration or working-data path")
    return Path(os.path.abspath(path))


class Config:
    def __init__(self, path: Path):
        self.path = plain_path(path)
        raw = self.path.read_bytes()
        if len(raw) > 100_000:
            raise ValueError("configuration exceeds size budget")
        self.sha256 = digest(raw)
        self.data = json.loads(raw)
        if self.data.get("schema") != SCHEMA:
            raise ValueError("unsupported autonomy configuration")
        self.repository = plain_path(Path(self.data["repository"]))
        if not self.repository.is_dir() or self.path.is_relative_to(self.repository):
            raise ValueError("operator configuration must be outside the repository")
        self.state = plain_path(Path(self.data["state_dir"]))
        if self.state.is_relative_to(self.repository):
            raise ValueError("runtime state must be outside the repository")
        self.planfile = self.data.get("planfile_project")
        if self.planfile:
            self.planfile = plain_path(Path(self.planfile))
            if self.planfile.is_relative_to(self.repository):
                raise ValueError("use a separate Planfile intake, preserving shared backlog")
        self.probes = self.data.get("probes", [])
        if not 1 <= len(self.probes) <= 20:
            raise ValueError("configure between one and twenty probes")
        ids = set()
        budget = 0
        for probe in self.probes:
            name = probe.get("id", "")
            if not isinstance(name, str) or not IDENTIFIER.fullmatch(name) or name in ids:
                raise ValueError("probe identifiers must be unique and bounded")
            ids.add(name)
            budget += self._command(probe)
            if probe.get("oracle", "exit") not in {"exit", "json"}:
                raise ValueError("unknown probe oracle")
            for field in ("failure_threshold", "recovery_threshold"):
                value = probe.get(field, 2)
                if type(value) is not int or not 1 <= value <= 100:
                    raise ValueError("invalid observation threshold")
            repair = probe.get("repair")
            if repair:
                budget += self._command(repair) + probe.get("timeout_seconds", 30)
                if not repair.get("authority_ref"):
                    raise ValueError("repair requires explicit operator authority")
                attempts = repair.get("max_attempts", 1)
                cooldown = repair.get("cooldown_seconds", 300)
                if type(attempts) is not int or not 1 <= attempts <= 3:
                    raise ValueError("repair attempt budget must be between one and three")
                if (type(cooldown) not in (int, float) or not math.isfinite(cooldown)
                        or not 1 <= cooldown <= 86400):
                    raise ValueError("invalid repair cooldown")
        if budget > 900:
            raise ValueError("cycle exceeds the fifteen-minute execution budget")

    def _command(self, spec: dict) -> int:
        argv = spec.get("argv")
        if (not isinstance(argv, list) or not argv or len(argv) > 100
                or any(not isinstance(v, str) or not v or len(v) > 4096 for v in argv)):
            raise ValueError("commands must be bounded argv arrays")
        executable = Path(argv[0])
        if not executable.is_absolute() or not os.access(executable, os.X_OK):
            raise ValueError("use an existing absolute executable path")
        cwd = plain_path(Path(spec.get("cwd", self.repository)))
        if not cwd.is_dir():
            raise ValueError("command cwd does not exist")
        timeout = spec.get("timeout_seconds", 30)
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= 300):
            raise ValueError("command timeout must be at most 300 seconds")
        return timeout

    def guard(self):
        plain_path(self.path)
        if digest(self.path.read_bytes()) != self.sha256:
            raise RuntimeError("operator configuration changed during cycle")


def _child_limits():
    # Bound diagnostic output even when a faulty command writes continuously.
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))


def run_command(spec: dict, repository: Path) -> dict:
    started = time.monotonic()
    timed_out = False
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(
                spec["argv"], cwd=spec.get("cwd", repository), stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True,
                preexec_fn=_child_limits,
            )
        except OSError:
            return {"ok": False, "code": "launch_failed", "exit_code": None,
                    "duration_ms": int((time.monotonic() - started) * 1000)}
        try:
            process.wait(timeout=spec.get("timeout_seconds", 30))
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # Kill surviving descendants too; a parent exiting is not completion
            # for a background writer in the private probe process group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        output.seek(0)
        raw = output.read(4 * 1024 * 1024)
    ok = process.returncode == 0 and not timed_out
    code = "passed" if ok else ("timeout" if timed_out else "exit_failed")
    if ok and spec.get("oracle", "exit") == "json":
        try:
            result = json.loads(raw)
            # A zero exit code does not prove the application's semantic result.
            ok = (isinstance(result, dict) and result.get("success") is True
                  and not result.get("error") and not result.get("errors")
                  and not result.get("failed")
                  and result.get("status") not in {"failed", "error"})
        except (ValueError, UnicodeError):
            ok = False
        code = "passed" if ok else "semantic_failed"
    return {"ok": ok, "code": code, "exit_code": process.returncode,
            "output_sha256": digest(raw), "output_bytes": len(raw),
            "duration_ms": int((time.monotonic() - started) * 1000)}


class Monitor:
    def __init__(self, config: Config, *, runner=run_command, clock=time.time, intake=None):
        self.config, self.runner, self.clock, self.intake = config, runner, clock, intake

    @contextmanager
    def _locked(self):
        state = plain_path(self.config.state)
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = plain_path(state / "cycle.lock")
        with lock.open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("another autonomy cycle owns the state") from exc
            database = plain_path(state / "incidents.sqlite")
            with sqlite3.connect(database) as db:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("CREATE TABLE IF NOT EXISTS incidents (key TEXT PRIMARY KEY, data TEXT NOT NULL)")
                yield db

    def _save(self, db, key, item):
        db.execute("INSERT OR REPLACE INTO incidents VALUES (?, ?)", (key, json.dumps(item)))
        db.commit()

    def _event(self, verb, **params):
        path = plain_path(self.config.state / "events.jsonl")
        if path.exists() and path.stat().st_size >= 5_000_000:
            backup = plain_path(path.with_suffix(".jsonl.1"))
            path.replace(backup)
        event = {"schema": "curllm.autonomy-event/v1", "at": self.clock(),
                 "config_sha256": self.config.sha256,
                 "dsl": {"verb": verb, "params": params}}
        with path.open("a") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

    def _probe(self, probe, verb="probe.run"):
        self.config.guard()
        result = self.runner(probe, self.config.repository)
        self._event(verb, probe=probe["id"], result=result)
        return result

    def _enqueue(self, db, key, item, probe):
        if item.get("ticket") or not self.config.planfile:
            return
        self.config.guard()
        dedupe = f"curllm:{key}:{item['episode']}"
        try:
            if self.intake:
                ticket = self.intake(dedupe, item, probe)
            else:
                from planfile import Planfile
                pf = Planfile(str(self.config.planfile))
                ticket = pf.create_ticket(
                    name=f"[curllm] {probe['id']} failed verification",
                    description=(f"Monitor evidence: {json.dumps(item['last_result'])}. "
                                 f"Operator configuration SHA256: {self.config.sha256}. "
                                 "Reproduce the configured probe in an owned worktree; "
                                 "allocate through the repository allocator, obtain controller "
                                 "lease admission, add a regression, verify and publish through "
                                 "independent Validator. Probe recovery alone is not delivery."),
                    priority="high", source={"tool": "curllm-autonomy"}, dedupe_key=dedupe,
                    labels=["curllm", "autonomy", "controller-admission-required"],
                ).id
            item["ticket"] = ticket
            item["handoff"] = "awaiting_controller"
            self._save(db, key, item)
            self._event("development.enqueue", probe=probe["id"], ticket=ticket,
                        state="awaiting_controller")
        except Exception as exc:
            # Retain the outbox for retry. Never publish raw exception contents.
            item["handoff"] = "outbox_pending"
            self._save(db, key, item)
            self._event("development.enqueue_failed", probe=probe["id"],
                        error_type=type(exc).__name__)

    def _repair(self, db, key, item, probe):
        repair = probe.get("repair")
        if (not repair or item["repair_state"] in {"running", "unknown", "verified"}
                or item["attempts"] >= repair.get("max_attempts", 1)
                or self.clock() < item["next_attempt_at"]):
            return
        self.config.guard()
        # Reserve durably BEFORE the effect. Crash recovery changes running to
        # unknown, requiring operator reconciliation instead of effect replay.
        item.update(repair_state="running", attempts=item["attempts"] + 1,
                    next_attempt_at=self.clock() + repair.get("cooldown_seconds", 300))
        self._save(db, key, item)
        self._event("repair.run", probe=probe["id"], attempt=item["attempts"],
                    authority_ref=repair["authority_ref"])
        result = self.runner(repair, self.config.repository)
        after = self._probe(probe, "probe.verify") if result["ok"] else result
        item["repair_state"] = "verified" if after["ok"] else "failed"
        item["last_result"] = after
        if after["ok"]:
            item.update(active=False, failures=0, recoveries=0)
        self._save(db, key, item)
        self._event("repair.result", probe=probe["id"], state=item["repair_state"],
                    result=after)

    def cycle(self) -> dict:
        results = []
        with self._locked() as db:
            self.config.guard()
            for probe in self.config.probes:
                key = digest(json.dumps([str(self.config.repository), probe], sort_keys=True).encode())
                row = db.execute("SELECT data FROM incidents WHERE key=?", (key,)).fetchone()
                item = json.loads(row[0]) if row else {
                    "probe": probe["id"], "active": False, "failures": 0,
                    "recoveries": 0, "attempts": 0, "episode": 0,
                    "repair_state": "idle", "next_attempt_at": 0, "ticket": None,
                    "handoff": "none",
                }
                if item["repair_state"] == "running":
                    item["repair_state"] = "unknown"
                result = self._probe(probe)
                item["last_result"] = result
                item["observed_at"] = self.clock()
                if result["ok"]:
                    item["failures"] = 0
                    item["recoveries"] += 1
                    if item["active"] and item["recoveries"] >= probe.get("recovery_threshold", 2):
                        item["active"] = False
                        self._event("incident.recovered", probe=probe["id"], ticket=item["ticket"])
                else:
                    item["recoveries"] = 0
                    item["failures"] += 1
                    if not item["active"] and item["failures"] >= probe.get("failure_threshold", 2):
                        item.update(active=True, episode=item["episode"] + 1,
                                    ticket=None, handoff="outbox_pending",
                                    repair_state="unknown" if item["repair_state"] == "unknown" else "idle")
                        self._event("incident.open", probe=probe["id"], episode=item["episode"], result=result)
                self._save(db, key, item)
                # Pending intake survives recovery; an effect is not a delivery receipt.
                if item["episode"] and not item["ticket"]:
                    self._enqueue(db, key, item, probe)
                if item["active"] and not result["ok"]:
                    self._repair(db, key, item, probe)
                results.append(item)
            summary = {"schema": "curllm.autonomy-cycle/v1", "config_sha256": self.config.sha256,
                       "healthy": all(item["last_result"]["ok"] for item in results),
                       "active_incidents": sum(item["active"] for item in results), "probes": results}
            self._event("cycle.completed", healthy=summary["healthy"], active_incidents=summary["active_incidents"])
            return summary

    def status(self) -> dict:
        with self._locked() as db:
            return {"schema": "curllm.autonomy-status/v1", "config_sha256": self.config.sha256,
                    "incidents": [json.loads(row[0]) for row in db.execute("SELECT data FROM incidents ORDER BY key")]}

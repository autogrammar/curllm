#!/usr/bin/env python3
"""Stage a merged release and optionally activate its bounded user timer."""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def safe_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked installation path")
    if any(c in str(path) for c in "\n\r\0"):
        raise ValueError("invalid installation path")
    return Path(os.path.abspath(path))


def command(argv, cwd=None):
    return subprocess.check_output(argv, cwd=cwd, stderr=subprocess.PIPE).decode().strip()


def merged_revision(repository, revision):
    sha = command(["git", "rev-parse", "--verify", "--end-of-options", revision + "^{commit}"], repository)
    subprocess.run(["git", "merge-base", "--is-ancestor", sha, "refs/remotes/origin/main"],
                   cwd=repository, check=True, capture_output=True)
    return sha


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_release(release):
    release = safe_path(release)
    record = json.loads(safe_path(release / ".autonomy-release.json").read_text())
    for name, expected in record["files"].items():
        path = safe_path(release / name)
        if not path.is_relative_to(release) or file_hash(path) != expected:
            raise ValueError("release source digest mismatch")
    return record


def export_release(repository, sha, release):
    release = safe_path(release)
    if release.exists():
        record = verify_release(release)
        if record["revision"] != sha:
            raise ValueError("release identity mismatch")
        return record
    release.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = subprocess.check_output(["git", "archive", sha], cwd=repository)
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=release.parent) as folder:
        stage = Path(folder)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar.getmembers():
                name = Path(member.name)
                if (name.is_absolute() or ".." in name.parts
                        or any(c in member.name for c in "\n\r\0")
                        or not (member.isfile() or member.isdir())):
                    raise ValueError("release archive has an unsupported entry")
            tar.extractall(stage, filter="data")
        required = ["curllm_core/autonomy.py", "curllm_core/cli/autonomy.py", "tests/test_autonomy.py"]
        if not all((stage / name).is_file() for name in required):
            raise ValueError("revision does not contain the autonomy runtime")
        files = {str(p.relative_to(stage)): file_hash(p) for p in sorted(stage.rglob("*")) if p.is_file()}
        record = {"schema": "curllm.autonomy-release/v1", "revision": sha, "files": files}
        (stage / ".autonomy-release.json").write_text(json.dumps(record, sort_keys=True) + "\n")
        # Absolute names let systemd check the merged source before Python starts.
        (stage / ".autonomy.sha256").write_text("".join(f"{value}  {release / name}\n" for name, value in files.items()))
        stage.rename(release)
    return verify_release(release)


def put_owned(path, content):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if path.read_text() != content:
            raise ValueError(f"existing operator file retained: {path}")
        return
    # Exclusive creation avoids replacing another installer/operator's file.
    with path.open("x") as stream:
        stream.write(content)


def systemd_quote(value):
    value = str(value)
    if any(c in value for c in "\n\r\0"):
        raise ValueError("invalid systemd argument")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def default_config(release, python, state):
    probes = []
    for name, test in [("browser-dsl", "tests/test_browser_control.py"),
                       ("mcp-v2", "tests/test_curllm_compat.py"),
                       ("autonomy", "tests/test_autonomy.py")]:
        probes.append({"id": name,
                       "argv": [str(python), "-m", "pytest", test, "-o", "addopts=", "-q", "--tb=short"],
                       "timeout_seconds": 180, "failure_threshold": 2, "recovery_threshold": 2})
    return {"schema": "curllm.autonomy-config/v1", "repository": str(release),
            "state_dir": str(state), "planfile_project": str(state / "development-intake"),
            "probes": probes}


def descriptors(release, python, config, interval):
    q = systemd_quote
    service = (
        "[Unit]\nDescription=Curllm continuous probes and verified repair\n\n"
        "[Service]\nType=oneshot\nUMask=0077\nTimeoutStartSec=16min\n"
        "Environment=PYTHONDONTWRITEBYTECODE=1\n"
        f"WorkingDirectory={str(release).replace('%', '%%')}\n"
        f"ExecStartPre=/usr/bin/sha256sum --status --check {q(release / '.autonomy.sha256')}\n"
        f"ExecStart={q(python)} -m curllm_core.cli.autonomy cycle --config {q(config)}\n"
    )
    timer = ("[Unit]\nDescription=Periodically verify curllm browser, DSL and MCP\n\n"
             f"[Timer]\nOnBootSec=2min\nOnUnitInactiveSec={interval}s\nAccuracySec=5s\n"
             "Unit=curllm-autonomy.service\n\n[Install]\nWantedBy=timers.target\n")
    return service, timer


def install(args):
    os.umask(0o077)
    repository = safe_path(args.repository)
    # Preserve the venv executable spelling: resolve() selects its global Python.
    python = Path(args.python).absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Python executable is unavailable")
    command([str(python), "-c", "import mcp.server.fastmcp,pytest,playwright,planfile"])
    if not 60 <= args.interval <= 86400:
        raise ValueError("timer interval must be between 60 and 86400 seconds")
    sha = merged_revision(repository, args.revision)
    release = safe_path(args.data_root) / "releases" / sha
    state = safe_path(args.state_root)
    config = safe_path(args.config_root) / "config.json"
    units = safe_path(args.unit_root)
    if args.activate and units != safe_path(Path.home() / ".config/systemd/user"):
        raise ValueError("activation requires the actual user systemd directory")
    for path in (release, state, config, units):
        if path.is_relative_to(repository):
            raise ValueError("install outside the repository checkout")
    record = export_release(repository, sha, release)
    service, timer = descriptors(release, python, config, args.interval)
    writes = [(config, json.dumps(default_config(release, python, state), indent=2) + "\n"),
              (units / "curllm-autonomy.service", service), (units / "curllm-autonomy.timer", timer)]
    # Inspect all existing operator files before the first write. Upgrades retain
    # previous source/configuration until the operator reconciles the new pin.
    for path, content in writes:
        path = safe_path(path)
        if path.exists() and path.read_text() != content:
            raise ValueError(f"existing operator file retained: {path}")
    for path, content in writes:
        put_owned(path, content)
    if args.activate:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "curllm-autonomy.timer"], check=True)
    receipt = {"schema": "curllm.autonomy-deployment/v1", "revision": sha,
               "release": str(release), "python": str(python), "config": str(config),
               "config_sha256": file_hash(config), "interval_seconds": args.interval,
               "activated": args.activate, "source_files": len(record["files"])}
    phase = "activated" if args.activate else "staged"
    put_owned(safe_path(args.data_root) / f"deployment-{sha}-{phase}.json", json.dumps(receipt, indent=2) + "\n")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).absolute().parent.parent)
    parser.add_argument("--revision", default="origin/main")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--data-root", type=Path, default=Path.home() / ".local/share/curllm-autonomy")
    parser.add_argument("--state-root", type=Path, default=Path.home() / ".local/state/curllm-autonomy")
    parser.add_argument("--config-root", type=Path, default=Path.home() / ".config/curllm-autonomy")
    parser.add_argument("--unit-root", type=Path, default=Path.home() / ".config/systemd/user")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(install(args), sort_keys=True))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Installation stopped; existing state retained ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

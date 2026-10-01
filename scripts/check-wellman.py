#!/usr/bin/env python3
"""Validate adopted metadata; the managed gate owns full repository governance."""
import argparse
import json
import sys
from pathlib import Path

from wellman import __version__
from wellman.adoption import register, safe_path
from wellman.docs_adoption import validate_adoption
from wellman.runner import ConformanceRunner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    try:
        root = safe_path(parser.parse_args().root)
    except (OSError, ValueError) as error:
        print(json.dumps({"valid": False, "findings": [{"code": "WELLMAN-ROOT", "message": str(error)}]}))
        return 1
    findings = []
    if __version__ != "0.20.37":
        findings.append({"code": "WELLMAN-VERSION", "message": "Install the pinned Wellman 0.20.37 runtime."})
    try:
        registration = register(root, standards=("wellmanifest/docs", "wellmanifest/agent"), dry_run=True)
        if registration["changed"]:
            findings.append({"code": "WELLMAN-REQUIREMENTS", "message": "Required standards or publication metadata are missing or stale."})
        problem = registration["localCiPublication"]["problem"]
        if problem:
            findings.append({"code": "GOV-LOCAL-CI-001", "message": problem})
        findings.extend(validate_adoption(root, required=True))
        findings.extend(f.to_dict() for f in ConformanceRunner(root).run_all() if f.severity == "ERROR")
    except (OSError, ValueError, UnicodeError) as error:
        findings.append({"code": "WELLMAN-METADATA", "message": str(error)})
    print(json.dumps({"valid": not findings, "root": str(root), "findings": findings,
                      "scope": "adopted metadata and implemented Wellman checks; not S3-S5 certification"}, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

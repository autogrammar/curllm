"""Operator interface: python -m curllm_core.cli.autonomy cycle|status --config PATH."""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

from curllm_core.autonomy import Config, Monitor


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded curllm autonomy and evidence")
    parser.add_argument("action", choices=["cycle", "status"])
    parser.add_argument("--config", type=Path, required=True, help="Operator configuration outside checkout")
    args = parser.parse_args(argv)
    os.umask(0o077)
    logging.basicConfig(stream=sys.stderr, force=True)
    try:
        monitor = Monitor(Config(args.config))
        result = monitor.cycle() if args.action == "cycle" else monitor.status()
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("healthy", True) else 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({"schema": "curllm.autonomy-error/v1", "error_type": type(exc).__name__,
                          "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

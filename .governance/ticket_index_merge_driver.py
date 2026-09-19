#!/usr/bin/env python3
"""Custom Git merge driver for Wellmanifest project/TICKETS.md and TODO.md tables.

Automatically resolves concurrent insertions into the AUTO:TICKET_INDEX section
by parsing, deduplicating, and numerically sorting ticket rows by ticket-NNN ID.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

START_MARKER = "<!-- AUTO:TICKET_INDEX:START -->"
END_MARKER = "<!-- AUTO:TICKET_INDEX:END -->"
ROW_PATTERN = re.compile(r"^[ \t]*\|[ \t]*\*\*ticket-([0-9]+)\*\*[ \t]*\|")


def extract_table_rows(content: str) -> tuple[str, list[str], str] | None:
    start_idx = content.find(START_MARKER)
    end_idx = content.find(END_MARKER)
    if start_idx == -1 or end_idx == -1 or start_idx >= end_idx:
        return None

    header_part = content[: start_idx + len(START_MARKER)]
    footer_part = content[end_idx:]
    middle = content[start_idx + len(START_MARKER) : end_idx]

    lines = middle.strip("\n").split("\n") if middle.strip("\n") else []
    return header_part, lines, footer_part


def parse_ticket_rows(lines: list[str]) -> tuple[list[str], dict[int, str]]:
    table_headers: list[str] = []
    ticket_rows: dict[int, str] = {}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        match = ROW_PATTERN.match(stripped)
        if match:
            ticket_id = int(match.group(1))
            ticket_rows[ticket_id] = stripped
        elif stripped.startswith("|") and (
            "Ticket ID" in stripped or ":---" in stripped or ":-" in stripped
        ):
            table_headers.append(stripped)

    return table_headers, ticket_rows


def merge_ticket_index_content(ancestor_text: str, current_text: str, other_text: str) -> str | None:
    curr_parts = extract_table_rows(current_text)
    other_parts = extract_table_rows(other_text)

    if not curr_parts or not other_parts:
        return None

    curr_header, curr_lines, curr_footer = curr_parts
    _, other_lines, _ = other_parts

    curr_th, curr_rows = parse_ticket_rows(curr_lines)
    other_th, other_rows = parse_ticket_rows(other_lines)

    headers = curr_th if curr_th else other_th

    all_tickets = set(curr_rows.keys()) | set(other_rows.keys())
    merged_rows: dict[int, str] = {}

    for t_id in all_tickets:
        if t_id in curr_rows and t_id in other_rows:
            c_row = curr_rows[t_id]
            o_row = other_rows[t_id]
            if c_row == o_row:
                merged_rows[t_id] = c_row
            else:
                c_score = sum(1 for part in c_row.split("|") if part.strip() and part.strip() != "-")
                o_score = sum(1 for part in o_row.split("|") if part.strip() and part.strip() != "-")
                merged_rows[t_id] = o_row if o_score >= c_score else c_row
        elif t_id in curr_rows:
            merged_rows[t_id] = curr_rows[t_id]
        else:
            merged_rows[t_id] = other_rows[t_id]

    sorted_rows = [merged_rows[t_id] for t_id in sorted(merged_rows.keys())]
    table_lines = headers + sorted_rows
    table_body = "\n" + "\n".join(table_lines) + "\n"

    return curr_header + table_body + curr_footer


def run_merge(ancestor_file: Path, current_file: Path, other_file: Path) -> int:
    try:
        current_text = current_file.read_text(encoding="utf-8")
        other_text = other_file.read_text(encoding="utf-8")
        ancestor_text = ancestor_file.read_text(encoding="utf-8") if ancestor_file.is_file() else ""
    except Exception:
        return subprocess.run(
            ["git", "merge-file", str(current_file), str(ancestor_file), str(other_file)]
        ).returncode

    merged_text = merge_ticket_index_content(ancestor_text, current_text, other_text)
    if merged_text is not None:
        current_file.write_text(merged_text, encoding="utf-8")
        return 0

    return subprocess.run(
        ["git", "merge-file", str(current_file), str(ancestor_file), str(other_file)]
    ).returncode


def self_test() -> int:
    ancestor = (
        "# Ticket index\n\n"
        "<!-- AUTO:TICKET_INDEX:START -->\n"
        "| Ticket ID | Spec |\n"
        "| :--- | :--- |\n"
        "| **ticket-100** | [`README.md`](./ticket-100/README.md) |\n"
        "<!-- AUTO:TICKET_INDEX:END -->\n"
    )
    current = (
        "# Ticket index\n\n"
        "<!-- AUTO:TICKET_INDEX:START -->\n"
        "| Ticket ID | Spec |\n"
        "| :--- | :--- |\n"
        "| **ticket-100** | [`README.md`](./ticket-100/README.md) |\n"
        "| **ticket-136** | [`README.md`](./ticket-136/README.md) |\n"
        "<!-- AUTO:TICKET_INDEX:END -->\n"
    )
    other = (
        "# Ticket index\n\n"
        "<!-- AUTO:TICKET_INDEX:START -->\n"
        "| Ticket ID | Spec |\n"
        "| :--- | :--- |\n"
        "| **ticket-100** | [`README.md`](./ticket-100/README.md) |\n"
        "| **ticket-127** | [`README.md`](./ticket-127/README.md) |\n"
        "<!-- AUTO:TICKET_INDEX:END -->\n"
    )
    merged = merge_ticket_index_content(ancestor, current, other)
    assert merged is not None
    assert "| **ticket-100** |" in merged
    assert "| **ticket-127** |" in merged
    assert "| **ticket-136** |" in merged
    pos_100 = merged.find("**ticket-100**")
    pos_127 = merged.find("**ticket-127**")
    pos_136 = merged.find("**ticket-136**")
    assert pos_100 < pos_127 < pos_136, f"Order error: {merged}"
    print("Self-test passed: ticket-100 < ticket-127 < ticket-136 sorted perfectly without conflict.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--self-test" in args:
        return self_test()
    if len(args) < 3:
        print(
            "Usage: ticket_index_merge_driver.py <ancestor-path> <current-path> <other-path>",
            file=sys.stderr,
        )
        return 2
    return run_merge(Path(args[0]), Path(args[1]), Path(args[2]))


if __name__ == "__main__":
    sys.exit(main())

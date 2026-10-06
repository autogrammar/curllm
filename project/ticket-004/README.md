# Ticket 004: Repair field detection and DSL outcomes

- **ID**: ticket-004
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-06

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested testing and repairing curllm on 2026-10-06. Planfile STARTER-017. Prerequisite ownership mapping merged through independently approved PR #9. Preserve unrelated primary-checkout changes.

## Acceptance criteria

- [x] AC-01: Detect focused editable fields and exact selectors; unavailable controls excluded.
- [x] AC-02: Required-query failures and retry recovery produce accurate aggregate outcomes.
- [x] AC-03: Chromium regressions, available unit tests and governance checked.

Validation: 25 real Chromium/DSL regressions passed (18 failed before the repair); native governance passed. Broader unit run: 388 passed, 30 failed, 1 skipped, 1 deselected. All 30 failures originate from the pre-existing missing curllm_core.dsl.executor_llm import; preserved in Planfile STARTER-018. MCP tools initialize and respond with the declared MCP 1.x dependency; stdout logging repair is tracked in STARTER-018. No live Willmux browser was modified.

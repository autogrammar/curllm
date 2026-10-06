# Ticket 005: Restore v2 execution and MCP transport

- **ID**: ticket-005
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-06

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested testing and repairing curllm on 2026-10-06. Planfile STARTER-018 captures failures from the requested tests. Ticket-004 merged through independently approved PR #10. Preserve primary-checkout changes and global MCP 2.x installation.

## Acceptance criteria

- [x] AC-01: Documented v2 imports and execute(instruction) use the existing executor.
- [x] AC-02: Dedicated MCP stdio output contains only protocol messages.
- [x] AC-03: Unit suite and native governance pass with declared dependencies.

Validation: 56 v2/transport tests passed; all three new regressions failed before repair. Broad unit suite with declared MCP SDK 1.30.0: 421 passed, 1 skipped, 1 external HTTP test deselected (100.81s). That HTTP test passed separately, for 422 distinct passing tests in total. Native governance passed with zero errors/warnings. Actual MCP stdio initialization, seven-tool discovery and interfaces response succeeded without JSON-RPC parsing errors. Global SDK 2.1.1 preserved; isolated SDK 1.x runtime used for tests.

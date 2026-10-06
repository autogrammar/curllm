# Ticket 009: Read autonomy status during running verification cycles

- **ID**: ticket-009
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user requested continued testing, fixes and deployment of curllm autonomy; bounded STARTER-021 correction follows observed status failure. STARTER-020 automatic coding admission remains blocked and preserved.

## Goal and scope

Operator status must return the last committed snapshot while verification owns the cycle lock, without creating or mutating monitor state. Preserve serial execution and config/path guards.

## Acceptance criteria

- [x] AC-01: Regressions cover concurrent writer, initial state and safe readback; all autonomy tests pass.
- [x] AC-02: Native validation passes; independent exact-head publication is the protected next step.
- [ ] AC-03: After merge, deployed status can be read during a real timer cycle; external receipt records the outcome.

Validation: four new regressions fail before the change; all 34 autonomy tests pass after it. Native governance passes. AC-03 is closed by post-merge external deployment evidence, without a repository closure commit.

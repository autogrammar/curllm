# Install continuous curllm monitoring

- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: governance

SESSION_EXECUTION_AUTHORIZATION: user explicitly requested implementation, testing, repairs and deployment of continuous improvement/autonomy in curllm on 2026-10-06. STARTER-019. Independent publication and activation of the bounded user timer authorized; preserve primary and foreign services/configuration. Automatic source development remains pending STARTER-020 protected controller admission.

## Acceptance criteria

- [x] AC-01: Installer admits merged source only and preserves existing operator files.
- [x] AC-02: Installer tests, native governance and staged runtime probes pass.
- [ ] AC-03: Activate timer after merge and retain real cycle/readback receipt.

Validation: seven installer tests passed; systemd-analyze verified both units. Actual merged-source canary cycle passed all three probes (25 browser/DSL, 3 MCP/v2, 30 autonomy tests); zero active incidents. Native governance passed. AC-03 is a post-merge runtime action and will be recorded in the external deployment receipt, without a repository closure commit.

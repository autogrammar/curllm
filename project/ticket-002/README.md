# Ticket 002: Adopt pinned Wellman validation

- **ID**: ticket-002
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-01

## Goal and scope

Register baseline, Agent and Docs requirements, adopt repository-bound Docs
metadata, and validate these contracts with pinned Wellman in local checks and CI.
Preserve the existing new-project pin and all product code.

## Acceptance criteria

- [x] AC-01: Wellman registration is idempotent; Docs metadata validates.
- [x] AC-02: The existing managed governance gate accepts the scoped changes.
- [x] AC-03: Missing or invalid requirements and Docs metadata fail validation.
- [ ] AC-04: Publish the exact tested head through the independent controller.

## Authorization

SESSION_EXECUTION_AUTHORIZATION: the owner requested installation, completion,
testing and merging of Wellmanifest adoption across Autogrammar repositories.
This authorizes implementation and the declared protected delivery route;
it is not trusted merge approval.

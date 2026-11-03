# Ticket 013: restore curllm api service on free port and proper cli error exits

- **ID**: ticket-013
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-03

## Goal and scope

Restore Curllm API service on a dedicated non-conflicting port (8020) with `/tmp/curllm_api_port` dynamic discovery, restore `/api/execute` probe response handling, and return structured JSON error envelopes for 404/5xx to ensure honest non-zero exit codes. Unblock curllm autonomy channel.

## Acceptance criteria

- [x] AC-01: Unit API aktywny, /api/execute odpowiada na probe.
- [x] AC-02: CLI zwraca niezerowy exit na 404/5xx (poprzez ustrukturyzowane koperty błędów JSON z polami `.error` i kodem HTTP).
- [x] AC-03: curllm-autonomy zgłasza healthy po cyklu.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

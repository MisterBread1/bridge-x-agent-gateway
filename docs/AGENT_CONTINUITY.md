# Agent continuity investigation — 12.13.0 candidate

[README](../README.md) · [Architecture](ARCHITECTURE.md) · [Doctor](DOCTOR.md) · [Testing](TESTING.md)

Investigation date: **2026-11-01**, Asia/Qyzylorda. Baseline: stable `v12.12.3`, commit `d1c509a4e533fa184e5b1494bc5cd8361162f90a`. This candidate adds public CLI/API diagnostics, so its intended version is **12.13.0**. The published stable tag is never moved.

## Evidence and limits

The supplied incident contains a Bash history marker, an empty-output description and an early final response. It contains no authenticated upstream trace, full client transcript, actual shell exit code or client finish-state capture. It does **not** establish that the marker caused the model's decision to stop.

Three deterministic regressions were executed against an isolated, tracked-file-only copy of the unchanged baseline. All three failed:

1. Five completed Bash pairs were serialized as only two native tool pairs; three older receipts became ordinary assistant text.
2. The exact reported `Completed client tool history` echo, followed by provider `Finish("stop")`, was accepted as HTTP 200 / `finish_reason: stop`.
3. The same echo in streaming mode ended in a normal stop and `[DONE]`.

The same tests pass after this change. This proves a **history provenance loss and terminal echo-validation defect**. The injected echo is a controlled protocol reproduction, not a reproduction of live model reasoning. It does not establish why the original external model produced that response. Tests assert pairing, values, ordering, dispatch absence and terminal transport behavior, rather than only checking a prompt phrase.

Remaining hypotheses for a prose-only early final include model interpretation of the old assistant summary, a client stop policy, omitted original goals after client-side compaction, or a different upstream/client terminal condition. Existing explicit length/error/unknown-finish guards remain active. A prose answer alone cannot distinguish intermediate commentary from true task completion.

## Exact request chain

| Stage | Responsibility and evidence |
|---|---|
| User task | Client supplies the original transcript and declared schemas. |
| Native proposal | Molab emits start/delta/available; incomplete input is rejected. |
| Dispatch | Gateway validates schema, allocates a local call ID and commits `DISPATCHED` before delivery. |
| Execution | ZCode/client applies permissions and runs the tool. Bridge X executes nothing. |
| Result | Client appends its assistant call and actual `role: tool` result with the local ID. |
| Reconciliation | Coordinator reconciles the original transcript into SQLite before compaction. |
| History serialization | Retained completed pairs stay `dynamic-tool`, `output-available`, with real input/output and ID. This replaces the defective older-pair-to-assistant-text conversion. |
| Next generation | Only a new client request starts it. There is no injected continuation message or generation loop. |
| Finish | Terminal failures override partial output. An anchored historical-tool echo is a protocol error, not a final answer. |
| Client state | Standard finish reasons remain; optional diagnostic metadata reports uncertainty. The gateway does not control the client's agent scheduler. |

## History and compaction

All retained paired calls use the existing supported native tool representation. No invented data-part type, placeholder input or successful receipt is introduced. This can retain more historical argument bytes than 12.12.3; the existing coordinator context budget remains the bound. Over-budget history removes only old complete exchanges, after receipt reconciliation, while protecting the first user goal, latest messages and pending arguments. Typed JSON receipt fields survive output elision. The caller's original transcript is never mutated. Raw old output is not backed up in SQLite; the client remains responsible for its full transcript.

Older completed commands are historical data, not new input-available proposals. Pending calls retain input-available state; they are not converted to completed output. The gateway accepts fresh executable actions only from validated provider events. Both the old legacy echo and the reported completed-history echo fail closed. Ordinary prose mentioning a marker does not become executable.

Repeated receipts remain one paired result. A later confirmed result can replace an unknown result; conflicting confirmed receipts fail with `TOOL_RECEIPT_CONFLICT`. User messages quoting historical markers remain intact.

## Empty Bash output and uncertain execution

| Actual client result | Classification |
|---|---|
| Integer `exit_code: 0`, empty stdout | `exit_zero` / `EXECUTED` |
| Integer nonzero exit, empty stdout | `exit_nonzero` / `FAILED` |
| Text only, or stdout only | `unknown` / `ACKNOWLEDGED` |
| Bash `success: true` without exit code | `unknown`; no shell exit status is invented |
| Explicit failure | `reported_failure` / `FAILED` |
| Explicit cancellation | `cancelled` / `CANCELLED` |
| Explicit timeout | `timed_out` / `TIMED_OUT` |
| No receipt after dispatch | Remains pending; `EXECUTION_UNKNOWN` recovery error |
| Duplicate received receipt | Idempotent; no new execution event |
| Later confirmed structured receipt after unknown text | Resolves the existing acknowledged operation; no execution is performed |

Generic non-shell tools retain explicit-success compatibility. Shell recognition currently covers Bash/Terminal/Shell/Exec names; arbitrary custom shell wrappers need a correctly structured client receipt and retain their own permission boundary.

The ledger persists a SHA-256 digest of canonical arguments, never the raw command. A repeated matching mutation with an unknown, cancelled or timed-out outcome is refused atomically, including after restart. A historical legacy operation without a digest is guarded conservatively by name. Read/search checks remain possible after an unknown acknowledged result; a read does not silently change the earlier shell exit status. Missing-receipt pending guards remain stricter. Inspect real state and return actual evidence; never clear a record or change session identity to bypass a recovery guard. This is not a proof of exactly-once execution by external clients or semantic equivalence between differently written commands.

## Public continuity diagnostics

Successful JSON completions and the terminal SSE chunk add `x_bridge_x`:

```json
{
  "agent_state": "model_stopped_unverified",
  "pending_operations": 0,
  "unknown_outcomes": 0,
  "task_completion_verified": false,
  "next_step": "client_decides_whether_to_continue"
}
```

Tool delivery uses `awaiting_tool_result` and `client_executes_tools`; an unresolved received outcome uses `execution_unknown`. Ordinary `stop` means the provider finished this response, not that an arbitrary task has been proved complete. Valid final answers are delivered once, without forcing a tool or looping. `required`, forced choice, `none`, parallel/serial schemas and plain chat retain their existing contracts. Clients may ignore this additive extension. Clients that enforce a closed response schema should update that schema.

Failures retain existing HTTP/SSE error contracts and are recorded as `recovery_required`. An error inside HTTP 200 never gets a fabricated `[DONE]`. Client disconnect closes generation and records cancellation; it cannot undo an already committed dispatch. Resume with original session/journal and receipts. Rate recovery remains bounded to explicit pre-output rejections. Runtime expiration is an external failure and is not repaired by retries.

## Sanitized event timeline

Events cover request receipt, provider generation, native proposal, dispatch, actual new receipt, outcome classification, compaction, provider finish, completion delivery, cancellation and recovery/failure. Replayed history does not generate duplicate receipt events. Fields are fixed categories, safe counters, generated/hashed correlation IDs and times. Commands, paths, model text, file content, headers, session identifiers and runtime URLs are excluded from normal event logs and the shareable report.

Existing `diagnostics` gains nullable metadata columns; `operations` gains nullable `argument_hash`. SQLite `user_version` migrates from 3 to 4 in the same journal. Existing rows, dispatch guards, operation events and rate metadata remain. Tests exercise old-schema upgrades and reopen. Doctor inspects old databases read-only and never migrates them.

## Validation and release gate

`tests/test_continuity.py` covers the baseline failure, empty shell outcomes, duplicate/recovered receipts, replay prevention, bounded history and pending input, valid final answers, uncertain finals, terminal errors and actual ASGI disconnect cancellation. `tests/test_doctor.py` covers offline behavior, private-value omission, dependency absence, busy ports, old SQLite read-only access, authenticated reports and an explicitly local network probe.

`python -m tools.continuity_acceptance` executes **Read → Edit → Read → Bash → Read → Edit → Bash → Final**, in JSON and SSE modes. It creates real temporary files, checks exact CSS and an unchanged neighbor, executes a fixed Python checker twice with genuinely empty stdout, proves each checker ran once, validates every retained native input/result pair and reopens SQLite on each of eight turns. Its upstream refuses to advance without all corresponding receipt values. It is a scripted native wire fixture, not live ZCode/Molab integration or a model reasoning benchmark.

The complete legacy regression suite, HTTP acceptance, native CSS acceptance, source/ZIP audits and a fresh extracted-ZIP environment are required before publication. The current investigation does **not** prove the original live semantic stop cause. Per the requested release gate, publish this work as a reviewable PR and **withhold a new release and merge** until an authorized live trace or similarly convincing evidence resolves that gap. The existing stable release remains available. Do not label scripted evidence as a live fix verification.

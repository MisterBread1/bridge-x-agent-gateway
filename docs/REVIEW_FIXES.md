# 12.13 audit repairs and release scope

The independent local review reproduced nine defects. Tests in `test_review_regressions.py` exercise these invariants against isolated journals and controlled upstreams; no operator configuration or live project is used.

| Defect | Repair and evidence |
|---|---|
| Unpaired generic success promoted to Bash success | Reclassify after the parent tool is known. Shell success requires a real integer exit code. |
| Confirmed results disagree across requests | Reject `TOOL_RECEIPT_CONFLICT` and roll back the entire reconciliation; preserve the first confirmed outcome. |
| Journal loss forgets pending assistant calls | Restore pending call metadata immediately, before generation, and enforce pending guards. |
| Cancelled/timed-out effects cannot recover | Accept real later exits; explicit stopped-execution/digest evidence records `RESOLVED_BY_CHECK`. |
| Anonymous sessions share a NULL bucket | Use only participating history call IDs for anonymous continuity and replay checks. |
| Readiness remains true after runtime 410 | Invalidate on connectivity failure; report timestamps and a 120-second freshness bound. Saving a different configuration invalidates old success. |
| SQLite waits block the event loop | A bounded single-worker actor serializes complete transactions off the event loop. Lock/unavailable errors have typed 503 envelopes; health remains responsive. |
| Newer schema version gets overwritten; event scans lack an index | Reject versions newer than 5 before migration and index call-event/scope lookups. |
| 100 repeated receipts cause 500 updates and 200 commits | One history transaction and change-only writes: regression asserts zero UPDATE statements and one commit for 100 exact duplicates. |

Additional user-reported regressions have dedicated tests: missing Node REPL display `title`, client history over 2 MB with oversized recent tool output, whole-exchange archival, preserved pending inputs, HTTP/SSE context rejection, one-attempt recovery limit and no recovery after partial output. Client schemas remain authoritative. Tests never claim a fixed model task succeeded merely because a finish event arrived.

The real local UI has authenticated route/configuration tests and browser inspection of an isolated fixture ledger. Rows come from SQLite; fixture actions are labeled offline and are not a live ZCode execution. Personal keys, runtime connection values and arbitrary model/file contents are excluded from safe exports.

The publication gate runs full source tests, HTTP cleanup, native CSS execution, long native receipt/restart acceptance, content audit, and the full suite in a newly extracted ZIP environment. It also installs the package and checks GUI assets/authentication and the CLI outside the checkout. Original stable/beta tags/assets remain immutable.

## SQLite runtime

Some bundled Python runtimes contain the upstream [SQLite WAL reset defect](https://sqlite.org/wal.html#wal_reset_bug). The journal selects rollback mode on affected versions; corrected SQLite branches can use WAL. Doctor reports the actual bundled SQLite version. Updating Python is preferable to replacing its SQLite DLL manually.

## Limits

The current live Molab runtime and installed ZCode long-task reasoning are not certified by scripted tests. The initial semantic stop cause remains a hypothesis beyond the reproduced protocol defects. The gateway cannot safely discard active user instructions, executable pending inputs or exact declared tool schemas, and cannot force ZCode's scheduler to continue. Persistent oversized active input receives an actionable typed error after safe compaction/recovery is exhausted. No new provider is added.

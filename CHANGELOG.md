# Changelog

This is a reconstructed history from the existing project changelog, regression reports, and public-release acceptance notes. It is not a claim of newly rerun historical tests or a complete release-by-release Git history. Earlier private reports are summarized here without publishing their transcripts, runtime identifiers, or local filesystem paths.

## Unreleased — Repository documentation

- Publication follow-up merges the documentation into main and adds offline Windows/Python 3.13 CI plus a validated, immutable beta publisher.
- The release builder now includes contribution/GitHub files, uses a fixed versioned prefix and timestamps, writes into a separate output directory, leaves the checkout manifest intact, and refuses replacing different existing assets. Four new packaging regressions cover these changes; gateway runtime behavior is unchanged.

- Exposes the source, tests, and tooling from the original tracked public ZIP as browsable repository files, preserving their bytes.
- Expands the README with an offline API example, navigation, structure, security, and evidence limits.
- Adds complete file/import guides, architecture flows, development/testing guidance, contribution instructions, and repository presentation notes.
- Clarifies local tool IDs, client-owned execution and verification, CLI/library defaults, adapter-specific terminal/error handling, and historical versus newly run checks.
- Retains the original ZIP as a frozen artifact; refreshes only the checkout's file manifest for the repository tree. No gateway behavior or dependency pins are changed.

## 12.12.3-beta.1 — Public release preparation

- Preserves native frontend tools, streaming, receipt reconciliation, execution scopes, and the SQLite operation ledger.
- Keeps bounded retries for explicit pre-output rate rejection, shared pacing, persistent recovery history, and one total request deadline.
- Keeps distinct errors for queue limits, runtime expiration, access denial, unreadable mode, and actual notebook code mode.
- Public copy adds a loopback port selector, offline configuration checking, a non-overwriting template command, pinned dependencies, offline CSS acceptance, and publication documentation. The working source installation is not modified.
- Optional Windows `start.bat` creates the local environment and installs pinned runtime dependencies when needed, then forwards arguments and the Python CLI's exit code.
- The earlier public-copy acceptance report is preserved in [docs/VALIDATION.md](docs/VALIDATION.md). Checks newly executed during repository documentation are recorded separately in [docs/DOCUMENTATION_QA.md](docs/DOCUMENTATION_QA.md).

### Working-source evidence versus public-copy evidence

The existing working-source report records **458 passed, 1 skipped**, plus a historical installed-ZCode recovery scenario with one locally injected initial 429 and subsequent live Molab work. The report records a successful repeat at approximately 194 seconds and preserves an earlier timed-out attempt as failed. These counts precede additional public CLI/configuration checks.

The separate public-release preparation report records **468 passed, 1 skipped** on Windows/Python 3.13.13, a fake-provider HTTP test, and scripted native CSS acceptance. Those public checks did not use installed ZCode or live Molab. The original launcher addition later preserved that suite result and separately checked `start.bat`; it did not claim another full-suite run.

The `12.12.3-beta.1` version remains unchanged by documentation. Upstream quotas/expiration, absolute deadlines, client permissions, and lack of current live certification remain visible limits.

## 12.12.2-beta.1

The report describes shared pacing, foreground priority, persistent cooldown, and ZCode-compatible retry metadata. It reports **431 passed, 1 skipped**, including a separately repeated clean extracted run. Historical installed-ZCode Read → Edit → Read → Bash and memory checks are reported successful. These are prior observations, not current live-provider verification.

## 12.12.1-beta.1

Independent memory execution scopes and serial native delivery address foreground/background receipt interference and forbidden parallel batches. The report records **402 passed, 1 skipped**. The historical installed-client main task and memory tools succeeded; a separate provider rate limit remained an explicitly recorded limitation.

## 12.12.0-beta.1 — Native frontend architecture

The adapter began supplying Molab frontend tool definitions, assembling native input events, and representing client tool results as native history. Manual/agent mode replaced notebook code mode for external client tools. Text command parsing remained a compatibility path.

The historical report records **389 passed, 1 skipped** and two successful installed-ZCode 0.17.1 Read → Edit → Read → Bash observations on temporary projects. Another attempt encountered an upstream rate limit and is not described as a success.

## 12.11.0-beta.1

The source changelog records receipt coordination, persistent operation states, idempotency protection, bounded terminal output, strict JSON/SSE boundaries, and isolated offline acceptance utilities.

This stage still used structured JSON text intents for Molab. The historical chat reports **367 passed, 1 skipped** and a live text-adapter Write/Python/result cycle. Native Molab tool support and installed-ZCode integration were not confirmed at that stage; they must not be attributed retroactively to it.

## 12.10.3

The root-cause audit records a fix to command dispatch: command markers in ordinary prose or source text no longer trigger a text-frame parser. Incomplete anchored commands remain invalid.

## 12.10.2 and 12.10.1

Schema-guided canonical integer normalization first covered typed text frames, then the narrow `Read.offset`/`Read.limit` exception for JSON/native representations. Other native/JSON argument types remained strict. The final schema check was retained.

## 12.7

The regression audit records stricter SSE EOF/UTF-8 boundaries, JSON and schema validation, late-error handling, and protection against incomplete tool delivery. These historical counts are not presented as current release results.

## Earlier prototypes and textual tool calls

The archived 12.6 README describes advisory small-action output guidance and the earlier `@@TOOL_CALL` text protocol. Existing early reports cover textual frames and JSON envelopes. More precise undocumented dates and changes are intentionally not reconstructed.

# Bridge X 12.13.1 — Stable

This patch repairs Windows startup when Python is installed but the project's `.venv` lacks pip, and makes Molab setup easier to find.

- `start.bat` uses standard bundled `ensurepip` to restore missing pip before installing requirements. New environments use the same bootstrap path. Existing environments, private configuration and journals are retained; global Python is not changed.
- Failures identify the actual stage: unavailable interpreter, invalid environment, failed pip bootstrap or failed dependency installation. Arguments and application exit codes pass through both Windows launchers.
- **`.molab.example` is included in the ZIP root and attached as a separate release download.** It contains placeholder-only JSON. Run `python -m tools.configure` in the extracted folder to create `.molab_local.json` without overwriting an existing file; replace the placeholders in that private copy. The empty server token is valid when the runtime does not require one. See the README configuration table.
- `SHA256SUMS.txt` covers both the complete ZIP and standalone example. Older release assets are not replaced.

Real Windows cmd/venv regressions exercise the exact missing-pip condition without package-network access, first startup, ensurepip failure and forwarded GUI arguments/exit codes. The release gate also runs the complete suite in source and a fresh extracted ZIP, plus installed-package GUI checks.

The 12.13.0 workbench, context and receipt repairs below are retained.

---

# Bridge X 12.13.0 — Stable

A local workbench, long-session repairs and durable client-tool recovery for the existing Molab/ZCode workflow. Existing v12.12.3 and beta assets remain unchanged.

- **Workbench:** `start-ui.bat` or `python -m bridge_x --ui`. Neutral compact layout, real operation history and inspector, explicit outcome checks, Molab connection setup, safe diagnostics. No mock session rows or client-tool executor.
- **Node REPL:** fill only the missing display title of the known Node JavaScript tool, then validate the complete client schema. Preserve supplied code and titles; never invent missing executable arguments.
- **Long sessions:** separate the 16 MB local input bound from the 1.5 MB upstream payload bound; compact large recent completed outputs and complete exchanges, preserve instructions and pending input, include schema overhead. One smaller retry follows an explicit pre-output context rejection. No retry follows partial output, pending native input or an uncertain failure.
- **Receipts:** reject contradictory confirmed outcomes across requests; restore pending history after journal loss; keep shell success without exit code unknown; accept actual later shell outcomes after cancellation/timeout. Explicit matching digest checks plus confirmation that execution stopped resolve uncertain consequences without inventing an exit code.
- **Storage:** one serialized journal worker keeps SQLite waits off the event loop. Whole-history transactions avoid repeated writes for known duplicate receipts. Schema 5 preserves existing state and rejects newer unknown schemas. Indexed event lookups and safe SQLite journaling improve sustained use.
- **Installation:** stable user data directory with explicit legacy discovery, one owner per CLI journal, personal GUI key and consistent backup command. A package can be installed with `python -m pip install .`; `bridge-x` becomes available in that environment.

The release workflow verifies source, a newly extracted ZIP, and the installed package with GUI assets before publication. Complete ZIP and SHA256SUMS are attached. [Upgrade and workbench guide](docs/WORKBENCH.md), [audit matrix](docs/REVIEW_FIXES.md), [investigation](docs/AGENT_CONTINUITY.md).

The model's original semantic reason for ending a task remains unproved. These repairs establish tested local protocol behavior; they do not certify every installed ZCode build or live Molab availability. Irreducibly oversized active instructions, tool registries or pending executable arguments still produce an actionable typed error. The gateway cannot safely discard those inputs or control ZCode's continuation scheduler.

The ZIP keeps the exact `.molab.example` filename. The separate GitHub asset is labeled `.molab.example` and downloads as `molab.example`, because GitHub strips leading periods from asset names. Rename that standalone copy to `.molab_local.json` for private setup, or use the complete ZIP and `python -m tools.configure`.

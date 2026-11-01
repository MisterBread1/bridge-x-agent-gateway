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

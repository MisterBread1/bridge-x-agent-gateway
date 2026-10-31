# Security

[README](README.md) · [Architecture boundaries](docs/ARCHITECTURE.md#security-boundaries) · [Safe debugging](docs/DEVELOPMENT.md#temporary-sqlite-and-safe-debugging)

Bridge X binds to loopback and authenticates model, diagnostic, capability, and operation endpoints with a local Bearer key. `/health` and `/ready` are unauthenticated status endpoints. A loopback listener is not a substitute for isolation from other software on the same computer.

Use a unique `BRIDGEX_LOCAL_KEY` for normal operation. The built-in `molab-local` key exists for compatibility and offline examples. Keep `.molab_local.json`, environment values, notebooks, journals, logs, and model transcripts outside public repositories. The release contains only clearly labeled demonstration configuration values.

The operator supplies upstream connection settings. No browser session extraction or credential harvesting is implemented. Diagnostic output must remain sanitized; do not post raw request bodies, headers, database files, or user configuration in issues.

The gateway validates proposals but does not execute tools. Client-side permissions and isolation remain necessary. Never treat a proposal, an unconfirmed dispatch, or a printed success claim as proof that an operation completed.

The local key is shared across authenticated endpoints; this release has no per-user isolation. Execution scopes coordinate foreground/background jobs and are not permission boundaries. Hash verification compares two values supplied by the client rather than independently inspecting the changed file. The test helper named `Sandbox` restricts temporary test paths and Python entry points; it is not an operating-system security boundary.

If a credential has already been published elsewhere, revoke or rotate it at its issuer. Removing it from one new archive does not invalidate the old credential or clean an earlier repository history. This release audit makes no claim about unknown previous publications.

Before sharing your own copy, exclude all local state, scan both the folder and ZIP, and review scanner findings without uploading source or secrets. The release's exact offline scan scope and known false positives are documented in `docs/VALIDATION.md`; no absolute absence guarantee is made.

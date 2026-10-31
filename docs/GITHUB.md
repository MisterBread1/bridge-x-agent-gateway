# Repository presentation and releases

[README](../README.md) · [Release notes](../RELEASE_NOTES.md) · [File guide](FILE_GUIDE.md) · [Documentation review](DOCUMENTATION_QA.md)

## Repository identity

Repository: [MisterBread1/bridge-x-agent-gateway](https://github.com/MisterBread1/bridge-x-agent-gateway).

Suggested About description:

> OpenAI-compatible AI agent gateway with native tool calling, SSE streaming, SQLite state recovery, and ZCode integration.

Suggested GitHub topics: `python`, `ai-gateway`, `openai-compatible`, `tool-calling`, `sse`, `sqlite`, `fastapi`, `ai-agents`, `zcode`.

These are proposed metadata values, not a claim that repository settings were updated. The connected GitHub tools used for this documentation work support repository reads and Git/PR writes, but do not expose About/topic mutation.

Feature summary: local Chat Completions gateway; validated client tool proposals; native frontend events; SSE error handling; persistent receipts and cooldowns. Keep beta status and offline/live evidence distinctions visible in any release description.

## Navigation

The root README is the entry point. Configuration answers operator questions; architecture and development explain extension points; testing distinguishes simulated providers from installed clients; the file guide is the exact inventory. The contribution guide and pull request template direct reviewers to concrete reproduction and validation evidence.

No CI workflow existed in the inspected default branch or original archive. This change does not fabricate CI status, publish a badge, or enable a new workflow. Future CI can start with the offline commands in [TESTING.md](TESTING.md), with Windows-specific skips reported explicitly.

## Preserved original artifact

`bridge-x-12.12.3-beta.1.zip` was already tracked on the default branch. It is retained byte-for-byte as the original distribution. The source files exposed by this change came from that exact archive; Python, tests, configuration template, dependencies, and launchers were not rewritten to document them.

The ZIP's original internal `FILE_SHA256SUMS.txt` covers that archive's files. The root manifest in this checkout is refreshed to cover the current tracked tree, including the preserved ZIP, excluding only the manifest itself. These are distinct snapshots. Later repository documentation is intentionally not advertised as being inside the frozen ZIP.

## Prepare a future release

1. Select a release version and source commit, preserve existing release assets, and review the working diff.
2. Run offline regressions and acceptance. Record platform, commands, failures/skips/warnings, and live checks only if separately authorized and actually performed.
3. Review `tools/build_release.py` before invoking it. Its allowlist omits arbitrary new root files and `.github/`; update and test it separately if the next ZIP should contain all repository documentation. The archive prefix uses the checkout directory name.
4. Build into a separate release location, audit the selected files and an extracted ZIP, and verify per-file and archive SHA-256. Do not include local settings, credentials, state, or transcripts.
5. Publish notes that clearly identify beta status and evidence limits, with an immutable source commit/tag and matching checksums. Creating GitHub release/tag assets is a separate action from this documentation PR.

## Optional demo media

No approved screenshots or GIFs were supplied. After a real, sanitized demo is recorded and approved, a future maintainer can add it below the README feature overview with descriptive alternative text. Verify visible editor paths, keys, prompts, and terminal content before publication. No placeholder image or invented demo is embedded here.

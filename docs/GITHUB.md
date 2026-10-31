# Repository presentation and releases

[README](../README.md) В· [Release notes](../RELEASE_NOTES.md) В· [File guide](FILE_GUIDE.md) В· [Documentation review](DOCUMENTATION_QA.md)

## Repository identity

Repository: [MisterBread1/bridge-x-agent-gateway](https://github.com/MisterBread1/bridge-x-agent-gateway).

Suggested About description:

> OpenAI-compatible AI agent gateway with native tool calling, SSE streaming, SQLite state recovery, and ZCode integration.

Suggested GitHub topics: `python`, `ai-gateway`, `openai-compatible`, `tool-calling`, `sse`, `sqlite`, `fastapi`, `ai-agents`, `zcode`.

The About description already matches this text. Topics remain suggested unless independently confirmed in repository settings. The connected GitHub tools support repository reads and Git/PR writes, but do not expose About/topic mutation.

Feature summary: local Chat Completions gateway; validated client tool proposals; native frontend events; SSE error handling; persistent receipts and cooldowns. Keep stable scope and offline/live evidence distinctions visible in any release description.

## Navigation

The root README is the entry point. Configuration answers operator questions; architecture and development explain extension points; testing distinguishes simulated providers from installed clients; the file guide is the exact inventory. The contribution guide and pull request template direct reviewers to concrete reproduction and validation evidence.

No CI workflow existed in the original archive. The repository now includes [offline CI](../.github/workflows/ci.yml) for Windows/Python 3.13 and a [validated release publisher](../.github/workflows/release.yml). Tests, pip consistency, temporary HTTP/SSE, native CSS acceptance, and archive auditing precede publication. Workflow files alone are not a passing CI claim; inspect the actual Actions run before citing it as evidence.

## Source and release artifacts

`bridge-x-12.12.3-beta.1.zip` was originally tracked on the default branch; its source was exposed for browsing by the documentation change. A later main-branch commit removed that binary from the source tree. The publication follow-up preserves that deletion and places downloadable assets in GitHub Releases. The original distribution remains in Git history; gateway modules, original tests, configuration template, dependency pins, and launcher are unchanged from its source.

The original ZIP's internal `FILE_SHA256SUMS.txt` covers its historical files. The root manifest in this checkout covers the current tracked source tree, excluding only the manifest itself. The new `bridge-x-12.12.3-complete.zip` release asset includes current source/docs, contribution guide, and GitHub configuration, with its own internal checksums. Private/generated local state and older binary archives are excluded.

## Prepare a future release

1. Select a release version and source commit, preserve existing release assets, and review the working diff.
2. Run offline regressions and acceptance. Record platform, commands, failures/skips/warnings, and live checks only if separately authorized and actually performed.
3. Use `python -m tools.build_release --output-dir artifacts` in a clean checkout. It selects complete allowlisted source/docs and uses a stable versioned archive root without changing the checkout's manifest.
4. Audit selected files and an extracted ZIP, and verify per-file and outer SHA-256. The builder refuses different pre-existing outputs. Do not include local settings, credentials, state, or transcripts.
5. The release workflow publishes tag `v<package version>`, version-appropriate notes, complete ZIP, and `SHA256SUMS.txt` only after its checks pass. It runs on main when the version or publisher changes, or manually. Existing releases/assets are not overwritten; use a new version for a new publication.

## Demo media

The README embeds the reviewed protocol-lanes GIF. A second execution-ledger option and exact scope are in [DEMO.md](DEMO.md). These are architecture illustrations grounded in the scripted native acceptance scenario, not screen recordings or installed-client certification.

## Community and owner-only settings

Structured bug/feature issue forms are provided; the publisher creates missing standard labels without altering existing ones. Topics, Discussions, and main protection require administrative access not exposed by the connected integration. See [COMMUNITY_SETUP.md](COMMUNITY_SETUP.md) for the exact settings and welcome-discussion draft. No disabled Discussions URL is added to the issue chooser.

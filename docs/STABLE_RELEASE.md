# Stable release verification — 12.12.3

[README](../README.md) · [Release notes](../RELEASE_NOTES.md) · [Testing](TESTING.md) · [Demo](DEMO.md)

Prepared on **2026-11-01** for a new `v12.12.3` release. The existing `v12.12.3-beta.1` tag, release, and assets are preserved. A stable label applies only to the verified local gateway behavior described here; it is not a claim of universal provider/client/platform support.

## Source and execution scope

The stable candidate starts from main commit `1fe7202d90c3b12142a8641256af04fb2ad81403`. Gateway algorithms and the Windows launcher are retained; the runtime metadata changes to `12.12.3`. Publication tooling gains strict ZIP verification, optional media support, community forms, and version-aware release flags. A separate PR is checked before merging.

No user gateway process is stopped, private Molab configuration is changed, or live model request is made. Native upstream events are simulated; the temporary test client performs actual file/Python actions. Read → Edit → Read → fixed Python check returns genuine fixture receipts. This is not an installed-ZCode or current live-Molab certification.

## Mandatory acceptance gate

The published ZIP must correspond to the exact tested main commit. Its archive manifest covers every member except itself; outer SHA-256 covers the ZIP. `tools.verify_release` rejects path escapes, wrong roots, duplicates, oversized input, and incomplete/mismatched manifests before extraction into its own temporary directory.

In a fresh Python environment created from the extracted ZIP, the gate performs:

1. Install `requirements-dev.txt`, including the pinned runtime closure.
2. `python -m pip check`.
3. `python -m compileall -q bridge_x bridge_x_test_runner tests tools`.
4. `python -m pytest -q -ra`, including SSE, native tools, receipts/SQLite reopen, explicit 429 recovery, cancellation, and malformed-stream boundaries.
5. `python LOCAL_HTTP_ACCEPTANCE.py` with its own temporary loopback server and journal.
6. `python -m tools.native_css_acceptance` with temporary files and real fixed Python execution.
7. `python -m bridge_x --provider fake --check-config`.

The release job first tests the source checkout, then independently repeats these checks from the ZIP. It publishes against `github.sha`, uses `--latest` for stable versions and `--prerelease --latest=false` for prerelease versions, and does not replace an existing release or asset.

### Completed local candidate acceptance

The extracted stable candidate was tested in a newly created Python 3.13.13 environment with newly installed pinned dependencies. All seven gate commands completed successfully. Full pytest reported **478 passed, 1 skipped, 1 warning in 85.13 seconds**. The skip was the existing Windows symlink-permission case; the warning was the existing Starlette/httpx test-client deprecation.

`pip check` and `compileall` passed. Real temporary HTTP/SSE acceptance reported graceful shutdown and successful SQLite reopen. Native CSS acceptance reported Read → Edit → Read → fixed Python execution, exit 0, exact CSS-only bytes, unchanged neighbor, preserved CRLF, and four returned receipts. Syntax-only startup reported **Bridge X 12.12.3**. The 98-member candidate had complete internal hashes and passed the publication scanner. Offline detect-secrets found only the existing reviewed synthetic marker, with no network credential verification.

Documentation validation resolved **224 relative links/anchors** across 18 Markdown files and parsed all five Mermaid diagrams; the guide matched 98 tracked paths. These are local candidate observations. Hosted PR/main checks and the final release asset must independently confirm the exact published commit; historical beta results are not substituted for that gate.

## GIF and documentation QA

Both committed GIFs are architecture illustrations, not screen recordings. They are 1100 × 680, 14.4 seconds, rendered at 12.5 FPS, loop forever, and remain below 0.4 MB each. Each stores 178 GIF frames (identical holds coalesced from 180 rendered frames) with 167 distinct images. Rendering checks text bounds; review inspected multiple decoded frames and the CSS before/after states. The final image matches the first for a continuous loop. The optional Pillow pin is excluded from gateway and test dependencies.

The publication audit accepts only the two explicitly named GIF paths as media; unrecognized binaries remain findings. Source/text and final extracted ZIP receive offline secret scanning. The known synthetic history-redaction marker in `test_regression_129.py` is not a credential and is retained as a reviewed warning.

The complete file guide, relative links, Mermaid diagrams, issue-form YAML, source/ZIP membership, and checksum manifests are verified before publishing. Actual run counts belong in the completed validation record and GitHub Actions logs, not copied from beta reports.

## Community and administrative scope

Issue forms are implemented in source; the release workflow creates only missing standard labels. The current integration returned HTTP 403 for branch-protection administration, Topics are empty, and Discussions is disabled. [COMMUNITY_SETUP.md](COMMUNITY_SETUP.md) provides exact owner steps and an English welcome-discussion draft. None of these unavailable administrative changes is presented as DONE.

## Known limits

External runtime expiration, quotas and provider interface changes remain external. Retries are bounded and never replay unknown client effects. Client receipts/hash verification are trusted client evidence. The scheduler is process-local; local-key authentication is not multi-user isolation. Other Python/OS combinations and long-running production loads are not newly certified. Warnings/skips are reported rather than suppressed.

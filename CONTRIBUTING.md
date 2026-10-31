# Contributing

Start with the [development guide](docs/DEVELOPMENT.md), [architecture](docs/ARCHITECTURE.md), and [test map](docs/TESTING.md). The project is currently **12.12.3-beta.1**; its compatibility limits are in the [release notes](RELEASE_NOTES.md).

## Report a reproducible problem

Include the Bridge X version, Python/OS version, selected provider mode, streaming/non-streaming choice, sanitized error code, and minimal reproduction using dummy values. State whether your test used a fake/mock upstream or a real installed client. Keep private configurations, keys, runtime addresses, raw requests, transcripts, logs, and databases out of issues. See [security guidance](SECURITY.md).

For uncertain tool effects, preserve the local journal and inspect the actual client result before attempting another mutation. A screenshot of a model claiming success is not an execution receipt.

## Submit a focused change

Use a separate branch. Describe the observable problem, final behavior, and commands actually run. Add a regression for executable behavior changes, and run the relevant suite followed by the full tests. Preserve receipt ownership, fail-closed stream handling, cancellation, and strict schema validation. Update documentation when a setting, endpoint, module, or file changes.

Documentation-only changes should resolve relative links, keep example commands consistent with the CLI, and account for every tracked file in [FILE_GUIDE.md](docs/FILE_GUIDE.md). Do not edit generated checksums manually, imply historical tests were rerun, or add a badge without real supporting infrastructure.

Live-provider and installed-client checks require explicit authorization and a disposable project. The normal contribution workflow uses offline tests.

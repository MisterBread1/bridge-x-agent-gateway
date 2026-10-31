# Community and repository administration

[README](../README.md) В· [Contributing](../CONTRIBUTING.md) В· [Repository presentation](GITHUB.md)

The connected GitHub integration can update source and workflows, but its administration access is insufficient for branch protection, Topics, and Discussions. The owner account's `admin: true` metadata does not grant the integration those scopes. An actual branch-protection read returned HTTP 403. No administrative restriction is bypassed here.

## Issue forms and labels

[Bug reports](../.github/ISSUE_TEMPLATE/bug_report.yml) require version, Python/OS, provider/transport mode, reproduction, sanitized code, and real/simulated environment. [Feature requests](../.github/ISSUE_TEMPLATE/feature_request.yml) collect use case, proposal, benefits, alternatives, and compatibility. [Chooser configuration](../.github/ISSUE_TEMPLATE/config.yml) links documentation until Discussions is actually enabled.

The main release workflow checks for `bug`, `enhancement`, `documentation`, and `question` labels and creates only missing labels. Existing label colors/descriptions are preserved. It uses issues-write only for this label setup; no issue or welcome post is sent automatically.

## Topics вЂ” owner action

On the repository Code page, use the gear beside **About**, then add:

`python` В· `ai-agents` В· `tool-calling` В· `coding-agent` В· `openai-api` В· `api-gateway` В· `sse` В· `sqlite` В· `zcode` В· `marimo`

Keep the existing About description: вЂњOpenAI-compatible AI agent gateway with native tool calling, SSE streaming, SQLite state recovery, and ZCode integration.вЂќ No homepage is invented.

## Discussions вЂ” owner action

1. Open repository **Settings в†’ General в†’ Features**, enable **Discussions**, and save.
2. Open **Discussions в†’ Categories**. Keep existing matching categories; create only missing **General**, **Q&A** (question/answer), **Ideas**, **Show and Tell**, and **Announcements**.
3. Publish the welcome text below in General or Announcements.
4. Only after the Discussions page is enabled, add its actual URL to the issue chooser. Do not direct users to an inactive page.

### Welcome discussion draft

**Welcome to Bridge X**

Bridge X is a local OpenAI-compatible AI agent gateway with native client tool calls, SSE streaming, and SQLite-backed receipt recovery. Start with the [README](https://github.com/MisterBread1/bridge-x-agent-gateway/blob/main/README.md), [configuration reference](https://github.com/MisterBread1/bridge-x-agent-gateway/blob/main/docs/CONFIGURATION.md), [architecture](https://github.com/MisterBread1/bridge-x-agent-gateway/blob/main/docs/ARCHITECTURE.md), and [testing guide](https://github.com/MisterBread1/bridge-x-agent-gateway/blob/main/docs/TESTING.md).

Use GitHub Issues for reproducible bugs and structured feature requests. Use Q&A for setup questions, Ideas for exploratory proposals, and Show and Tell for examples. State whether your environment uses a simulated provider or an authorized live client. Do not share tokens, cookies, private runtime URLs, raw headers, transcripts, or journal files.

## Protect main вЂ” owner action after the stable PR merges

Create a branch ruleset targeting the default branch, or use **Settings в†’ Branches в†’ Add branch protection rule** for `main`:

| Setting | Value |
|---|---|
| Require pull request before merging | Enabled. |
| Required approving reviews | **0**; do not require another person for a sole-owner repository. |
| Require status checks | Enabled; choose the actual **`regression`** job from **Offline regression checks**, after its successful run appears. |
| Require branches to be up to date | Enabled if it fits the owner's update workflow. |
| Require conversation resolution | Enabled. |
| Allow force pushes | Disabled. |
| Allow deletions | Disabled. |

The publisher reads trusted main and creates a tag/release; it never pushes back to main, so this protection does not require a bypass token. Do not select the release job as a required PR check: it runs only on main. Verify the enabled rule and a normal PR before declaring protection complete.

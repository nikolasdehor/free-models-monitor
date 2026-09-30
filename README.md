# free-models-monitor

Tracks zero-priced OpenRouter models and legacy manual Groq candidates, tells you when one gets
added or removed, and suggests (or applies) a fallback swap. Works
standalone via cron, or as a skill for any agent harness.

## Install

```bash
pip install git+https://github.com/nikolasdehor/free-models-monitor.git
```

Or run straight from a clone, no install:

```bash
git clone https://github.com/nikolasdehor/free-models-monitor.git
cd free-models-monitor
python3 -m free_models_monitor.monitor --init
```

## Quick start

```bash
# First run: takes a snapshot, does not alert
free-models-monitor --init

# Later runs: compares against the snapshot
free-models-monitor
```

Exit codes: `0` no change, `2` change detected, `1` error (network, bad
config).

## What it does

- Fetches OpenRouter's model catalog (`/api/v1/models`), keeps entries
  priced at zero for both prompt and completion.
- Includes a legacy manual Groq candidate list with explicit unverified metadata;
  these candidates are excluded from automatic fallback suggestions.
- Compares against the last snapshot (`~/.free-models-monitor/snapshot.json`
  by default) and reports additions and removals.
- Keeps a capped history (200 entries) of every change (`history.json`).
- Applies a banlist (`banned.json`) so models you never want suggested stay
  excluded.
- Suggests a fallback for a removed model, using a preference chain
  (`providers.py`, overridable with `--fallback-chain-file`) filtered by
  minimum context length.
- Optionally scans directories of agent configs (`--scan-dir`, repeatable)
  to flag which configs reference a removed model.
- Optionally notifies Telegram, Discord, Slack, or a generic webhook,
  reading credentials only from environment variables.

## Options

| Flag | Default | Purpose |
|---|---|---|
| `--state-dir` | `$FMM_STATE_DIR` or `~/.free-models-monitor` | where snapshot/history/banned files live |
| `--scan-dir DIR` (repeatable) | none | directories of agent configs to check for affected agents |
| `--providers` | `openrouter,groq` | comma-separated provider list |
| `--format` | `text` | `text` (chat-friendly, no markdown) or `json` |
| `--min-context` | `32768` | minimum context length for a fallback suggestion |
| `--notify` | `none` | `telegram`, `discord`, `slack`, `webhook`, or `none` |
| `--notify-always` | off | notify even when nothing changed |
| `--init` | off | (re)write the snapshot without reporting a change |
| `--fallback-chain-file` | none | JSON file overriding the default fallback preference order |

## Notification setup

Set only the variables for the channel you use:

| Channel | Env vars |
|---|---|
| `telegram` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `discord` | `DISCORD_WEBHOOK_URL` |
| `slack` | `SLACK_WEBHOOK_URL` |
| `webhook` | `WEBHOOK_URL` (receives `{"text": "..."}` as a JSON POST) |

## Switching a model everywhere it's used

```bash
# Preview
free-models-switch --from "openrouter/old-model:free" --to "openrouter/new-model:free" --file agent1.json --file agent2.json --dry-run

# Apply (backs up each file first, as <file>.bak-<timestamp>)
free-models-switch --from "openrouter/old-model:free" --auto --file agent1.json --apply
```

`--auto` picks the replacement from the fallback chain using the last
snapshot.

## Works with

- **OpenClaw**: [adapters/openclaw](adapters/openclaw), cron job template
  and persona.
- **Hermes Agent**: [adapters/hermes](adapters/hermes), cron and skill
  setup.
- **Claude Code / Codex / OpenCode**: [adapters/claude-code](adapters/claude-code),
  use `SKILL.md` directly.
- **Plain cron, no agent**: [adapters/cron](adapters/cron), a `crontab`
  entry with `--notify`.

Every one of these calls the same two commands (`free-models-monitor`,
`free-models-switch`); the adapters only differ in how they're scheduled
and how they deliver the report.

## As an agent skill

`SKILL.md` at the repo root documents how any agent (not just the harnesses
above) should run the monitor, read its output, and act on it. Copy it into
your harness's skills directory, or point your harness at this repo.

## Development

```bash
ruff check .
python3 -m unittest discover -s tests -v
```

pt-BR: see [README.pt-BR.md](README.pt-BR.md).

## License

MIT, see [LICENSE](LICENSE).

## Provider failures and catalog provenance

See [catalog reliability](docs/catalog-reliability.md) for partial failures, cache behavior, exit codes, JSON fields and Groq limits.

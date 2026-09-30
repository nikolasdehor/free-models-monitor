---
name: free-models-monitor
description: Checks whether zero-priced OpenRouter models and legacy manual Groq candidates were added or removed since the last run, and helps decide what to do about it (notify, suggest a fallback, or apply a config swap). Use whenever the user asks to check free model status, run the model monitor, or handle a model that stopped being free.
---

# free-models-monitor

This skill wraps two CLI tools that live in this repository:
`free_models_monitor.monitor` (the check) and `free_models_monitor.switch`
(the fix). They are plain Python 3.9+, stdlib only, and behave the same way
in any agent harness, or with no agent at all.

## 1. Run the monitor

```bash
python3 -m free_models_monitor.monitor --format json
```

First time on a machine, initialize instead so it does not report every
existing free model as "added":

```bash
python3 -m free_models_monitor.monitor --init
```

Add `--scan-dir <path>` (repeatable) for every directory that holds your
agent configs, so a removal can be matched to the configs that reference it.

Read the exit code before reading the output:

- `0`: nothing changed. Nothing else to do.
- `2`: something changed. Read the JSON body.
- `1`: the check failed or is incomplete (including partial provider failure) (network error, bad state dir). Report the
  stderr message to the user; do not treat this as "no free models".

## 2. Interpret the output

Read `complete`, `errors`, `provider_status` and `catalog_metadata` first. An incomplete check returns 1, retains failed providers from cache, and suppresses notifications. Cached/unverified Groq candidates are not confirmed available/free fallbacks. See `docs/catalog-reliability.md`.

With `--format json` the body has:

```json
{
  "changed": true,
  "changes": [{"type": "added", "model_id": "...", "model_info": {"name": "...", "context_length": 0}}],
  "affected_configs": {"<model_id>": [{"file": "/path/to/config", "agent": "relative/path"}]},
  "switches": [{"from": "...", "to": "...", "to_name": "..."}],
  "provider_counts": {"openrouter": 0, "groq": 0}
}
```

`changes[].type` is either `"added"` or `"removed"`.

- `type: "added"`: informational. Mention it, no action needed.
- `type: "removed"`: this is the case that matters. Check `affected_configs`
  for that model id, and `switches` for the suggested replacement.

Use `--format text` instead when the output goes straight into a chat
message (Telegram, WhatsApp, Slack), it is plain text, no markdown.

## 3. Decide what to do about a removal

1. If `affected_configs` lists files for the removed model, tell the user
   which configs are affected before changing anything.
2. If a `switches` entry has a `to` value, that is the suggested
   replacement. If `to` is null, no fallback was found, say so plainly
   instead of guessing a model id.
3. Only change a config file with explicit confirmation, unless the user
   has already told this skill to auto-apply. To apply:

```bash
python3 -m free_models_monitor.switch \
  --from "<removed model id>" \
  --to "<replacement model id>" \
  --file /path/to/config1 --file /path/to/config2 \
  --apply
```

   This backs up each file first (`<file>.bak-<timestamp>`) and only then
   edits it. Omit `--apply` (or pass `--dry-run`) to show the plan without
   touching anything.
4. If the harness needs a restart or reload after a config swap (OpenClaw's
   gateway, for example), that step belongs to the harness adapter, not to
   this skill. Check `adapters/<your-harness>/README.md` in this repository.

## 4. Notify, if asked to

If the user wants proactive alerts instead of on-demand checks, either:

- Let this skill's harness scheduler (cron, `/loop`, a harness's own cron
  equivalent) call `python3 -m free_models_monitor.monitor --notify
  <channel>` on a schedule, with the channel's credentials in the
  environment (see `README.md`, "Notification setup"). The tool only
  notifies when something changed, unless `--notify-always` is set.
- Or run the check yourself in the conversation and relay the result if the
  user is asking interactively.

## Harness-specific setup

This skill only covers the CLI. For how to install and schedule this repo
inside a specific harness, see:

- `adapters/openclaw/README.md`
- `adapters/hermes/README.md`
- `adapters/claude-code/README.md`
- `adapters/cron/README.md`

#!/usr/bin/env python3
"""Portable monitor for free-tier LLM models across providers.

Tracks zero-priced OpenRouter models and manual Groq candidates between runs,
reports what was added
or removed, suggests a fallback per a preference chain, and can notify
Telegram/Discord/Slack/a generic webhook. Works standalone via cron or as
an agent skill in any harness, see SKILL.md at the repo root.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from free_models_monitor import notify as notify_mod
from free_models_monitor.providers import (
    DEFAULT_FALLBACK_CHAIN,
    GROQ_CATALOG_METADATA,
    fetch_groq_free,
    fetch_openrouter_free,
)

HISTORY_CAP = 200
DEFAULT_MIN_CONTEXT = 32768
SCAN_EXTENSIONS = (".md", ".json", ".yaml", ".yml", ".toml")


def default_state_dir():
    return os.environ.get("FMM_STATE_DIR") or os.path.expanduser(
        "~/.free-models-monitor"
    )


def normalize_model_id(model_id):
    """Adds the openrouter/ prefix config files use to key OpenRouter ids."""
    if model_id.startswith("openrouter/") or model_id.startswith("groq/"):
        return model_id
    return f"openrouter/{model_id}"


def denormalize_model_id(model_id):
    if model_id.startswith("openrouter/"):
        return model_id[len("openrouter/") :]
    return model_id


def load_json_safe(path, default=None):
    default = {} if default is None else default
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def save_json_safe(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_banned_models(state_dir):
    data = load_json_safe(os.path.join(state_dir, "banned.json"), {"banned_models": []})
    return set(data.get("banned_models", []))


def load_fallback_chain(path):
    if not path:
        return list(DEFAULT_FALLBACK_CHAIN)
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        return list(data.get("fallback_chain", []))
    return list(data)


def fetch_current_models(providers, banned):
    """Fetches and merges free models across the requested providers."""
    current, counts, errors = {}, {}, []
    if "openrouter" in providers:
        or_free, err = fetch_openrouter_free()
        if err:
            errors.append(err)
        else:
            filtered = {
                normalize_model_id(mid): info
                for mid, info in or_free.items()
                if normalize_model_id(mid) not in banned and mid not in banned
            }
            current.update(filtered)
            counts["openrouter"] = len(filtered)
    if "groq" in providers:
        groq_free, err = fetch_groq_free()
        if err:
            errors.append(err)
        else:
            filtered = {k: v for k, v in groq_free.items() if k not in banned}
            current.update(filtered)
            counts["groq"] = len(filtered)
    return current, counts, errors


def find_agents_using_model(model_id, scan_dirs):
    """Walks scan_dirs looking for files that reference model_id."""
    affected = []
    needles = {model_id, denormalize_model_id(model_id)}
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for root, _dirs, files in os.walk(scan_dir):
            for fname in files:
                if not fname.endswith(SCAN_EXTENSIONS):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue
                if any(n in content for n in needles):
                    affected.append(
                        {"file": fpath, "agent": os.path.relpath(fpath, scan_dir)}
                    )
    return affected


def find_best_fallback(
    current, fallback_chain, banned, exclude_model=None, min_context=DEFAULT_MIN_CONTEXT
):
    """Picks a replacement model: chain order first, then highest context."""
    exclude = (
        {exclude_model, denormalize_model_id(exclude_model)} if exclude_model else set()
    )
    current = {mid: info for mid, info in current.items()
               if info.get("free_tier_verified", True)}
    for model_id in fallback_chain:
        if model_id in exclude or model_id in banned:
            continue
        info = current.get(model_id)
        if info and info.get("context_length", 0) >= min_context:
            return model_id, info
    by_context = sorted(
        current.items(), key=lambda kv: kv[1].get("context_length", 0), reverse=True
    )
    for model_id, info in by_context:
        if model_id in exclude or model_id in banned:
            continue
        if info.get("context_length", 0) >= min_context:
            return model_id, info
    return None, None


def add_history_entry(history, change_type, model_id, model_info, details=None):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": change_type,
        "model_id": model_id,
        "model_info": model_info,
    }
    if details:
        entry["details"] = details
    history.setdefault("changes", []).append(entry)
    history["changes"] = history["changes"][-HISTORY_CAP:]
    return history


def build_report_text(changes, affected_by_model, switches, now_label):
    lines = [f"ALERT: change detected in free models monitor ({now_label})"]
    switch_by_from = {s["from"]: s for s in switches}
    for change in changes:
        mid, info = change["model_id"], change["model_info"]
        if change["type"] == "removed":
            lines += [
                "",
                "Model REMOVED from " + ("manual Groq catalog:" if mid.startswith("groq/") else "free tier:"),
                f"  - {mid} ({info.get('name', mid)})",
            ]
            for a in affected_by_model.get(mid, []):
                lines.append(f"  affected config: {a['file']}")
            switch = switch_by_from.get(mid)
            if switch and switch["to"]:
                lines.append(f"  suggested switch: {mid} -> {switch['to']}")
            elif switch:
                lines.append("  suggested switch: FAILED - no fallback found")
        elif change["type"] == "added":
            ctx = info.get("context_length", 0)
            lines += [
                "",
                "Model ADDED to " + ("manual Groq catalog:" if mid.startswith("groq/") else "free tier:"),
                f"  + {mid} ({info.get('name', mid)}, ctx={ctx})",
            ]
    return "\n".join(lines)


def compute_diff(
    current, snapshot, scan_dirs, fallback_chain, banned, min_context, history, fallback_current=None
):
    """Diffs current against the previous snapshot, updating history in place."""
    normalized_snapshot = {
        normalize_model_id(mid): info for mid, info in snapshot.items()
    }
    new_models = {k: v for k, v in current.items() if k not in normalized_snapshot}
    removed_models = {k: v for k, v in normalized_snapshot.items() if k not in current}

    changes, affected_by_model, switches = [], {}, []

    for mid, info in new_models.items():
        changes.append({"type": "added", "model_id": mid, "model_info": info})
        history = add_history_entry(history, "added", mid, info)

    for mid, info in removed_models.items():
        changes.append({"type": "removed", "model_id": mid, "model_info": info})
        history = add_history_entry(history, "removed", mid, info)
        affected_by_model[mid] = find_agents_using_model(mid, scan_dirs)
        fb_id, fb_info = find_best_fallback(
            current if fallback_current is None else fallback_current,
            fallback_chain, banned, exclude_model=mid, min_context=min_context
        )
        if fb_id:
            switches.append(
                {"from": mid, "to": fb_id, "to_name": fb_info.get("name", fb_id)}
            )
            history = add_history_entry(
                history,
                "switch_suggested",
                mid,
                {"name": fb_info.get("name", "unknown")},
                details=f"{mid} -> {fb_id}",
            )
        else:
            switches.append({"from": mid, "to": None, "to_name": None})

    return changes, affected_by_model, switches, history


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="free-models-monitor",
        description="Track free LLM model availability across providers.",
    )
    p.add_argument("--state-dir", default=None)
    p.add_argument("--scan-dir", action="append", default=[])
    p.add_argument("--providers", default="openrouter,groq")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--min-context", type=int, default=DEFAULT_MIN_CONTEXT)
    p.add_argument(
        "--notify",
        choices=["telegram", "discord", "slack", "webhook", "none"],
        default="none",
    )
    p.add_argument("--notify-always", action="store_true")
    p.add_argument("--init", action="store_true")
    p.add_argument("--fallback-chain-file", default=None)
    args = p.parse_args(argv)
    selected = {name.strip() for name in args.providers.split(",") if name.strip()}
    if not selected or selected - {"openrouter", "groq"}:
        p.error("--providers must select openrouter and/or groq")
    return args


def reconcile_providers(current, counts, snapshot, providers):
    """Retain unavailable/disabled providers; successful empty catalogs replace cache."""
    preserved = {
        normalize_model_id(mid): info for mid, info in snapshot.items()
        if normalize_model_id(mid).split("/", 1)[0] not in counts
    }
    status = {}
    for provider in sorted(providers):
        if provider in counts:
            status[provider] = "fresh" if provider != "groq" else "static_unverified"
        else:
            cached = any(mid.startswith(provider + "/") for mid in preserved)
            status[provider] = "cached" if cached else "unavailable"
    return {**preserved, **current}, status


def render_report(args, changes, affected, switches, counts, status, errors, now, size, initialized):
    if args.format == "json":
        return json.dumps({
            "changed": bool(changes), "changes": changes, "affected_configs": affected,
            "switches": switches, "provider_counts": counts, "provider_status": status,
            "complete": not errors, "errors": errors, "initialized": initialized,
            "catalog_metadata": {"groq": GROQ_CATALOG_METADATA} if "groq" in status else {},
        }, indent=2, ensure_ascii=False)
    if initialized:
        report = f"free-models-monitor: initialized with {size} catalog entries ({now})"
    elif changes:
        report = build_report_text(changes, affected, switches, now)
    else:
        report = f"free-models-monitor: no observed changes ({now}). {size} catalog entries tracked."
    if "groq" in status:
        report += ("\nGroq: manual legacy candidates; availability/free-tier eligibility "
                   "unverified (reviewed 2026-09-30).")
    if errors:
        report += "\nINCOMPLETE: failed providers retained from cache where available; see errors."
    return report


def collect_check(args, state_dir):
    snapshot_path = os.path.join(state_dir, "snapshot.json")
    history_path = os.path.join(state_dir, "history.json")
    providers = {p.strip() for p in args.providers.split(",") if p.strip()}
    banned = load_banned_models(state_dir)
    chain = load_fallback_chain(args.fallback_chain_file)
    snapshot = load_json_safe(snapshot_path, {})
    history = load_json_safe(history_path, {"changes": []})
    fresh, counts, errors = fetch_current_models(providers, banned)
    current, status = reconcile_providers(fresh, counts, snapshot, providers)
    initialized = args.init or not os.path.exists(snapshot_path)
    if initialized:
        changes, affected, switches = [], {}, []
        if counts:
            history = add_history_entry(history, "init", "all", {"count": len(current)})
    else:
        # Cached and unverified candidates must never be suggested as confirmed fallbacks.
        fallback = {mid: info for mid, info in fresh.items()
                    if not mid.startswith("groq/") or info.get("free_tier_verified", True)}
        changes, affected, switches, history = compute_diff(
            current, snapshot, args.scan_dir, chain, banned, args.min_context, history,
            fallback_current=fallback,
        )
    if counts:
        save_json_safe(snapshot_path, current)
        save_json_safe(history_path, history)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report = render_report(args, changes, affected, switches, counts, status, errors,
                           now, len(current), initialized)
    return report, bool(changes), errors


def main(argv=None):
    args = parse_args(argv)
    report, changed, errors = collect_check(args, args.state_dir or default_state_dir())
    print(report)
    for err in errors:
        print(f"WARNING: {err}", file=sys.stderr)
    # An incomplete check is an error even if a healthy provider changed.
    if not errors and args.notify != "none" and (changed or args.notify_always):
        ok, notify_err = notify_mod.notify(args.notify, report)
        if not ok:
            print(f"WARNING: notify failed: {notify_err}", file=sys.stderr)
    return 1 if errors else (2 if changed else 0)


if __name__ == "__main__":
    sys.exit(main())

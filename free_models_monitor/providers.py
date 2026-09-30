"""Provider adapters: zero-priced catalogs and unverified legacy candidates.

Add a new provider by writing a fetch_<name>_free() -> (dict, error)
function below and registering it in PROVIDERS. monitor.py only calls
functions from here, it never talks to a provider API directly.
"""
import copy
import json
import math
import urllib.error
import urllib.request

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
USER_AGENT = "free-models-monitor/1.0"

# Preference order for automatic fallback suggestions. Overridable via
# --fallback-chain-file (a JSON list, or {"fallback_chain": [...]}).
DEFAULT_FALLBACK_CHAIN = [
    "openrouter/qwen/qwen3-next-80b-a3b-instruct:free",
    "openrouter/openai/gpt-oss-120b:free",
    "openrouter/meta-llama/llama-3.3-70b-instruct:free",
    "openrouter/nousresearch/hermes-3-llama-3.1-405b:free",
    "openrouter/qwen/qwen3-coder:free",
    "openrouter/moonshotai/kimi-k2:free",
    "openrouter/openai/gpt-oss-20b:free",
    "openrouter/meta-llama/llama-3.2-3b-instruct:free",
    "groq/llama-3.3-70b-versatile",
]

# Legacy manual candidates, NOT a verified current/free catalog.
# Groq's authenticated /models endpoint lists active models, not free eligibility.
GROQ_CATALOG_METADATA = {
    "source": "legacy_manual_candidates", "reviewed_at": "2026-09-30",
    "catalog_as_of": None, "free_tier_verified": False,
    "models_docs": "https://console.groq.com/docs/models",
    "rate_limits_docs": "https://console.groq.com/docs/rate-limits",
    "note": "Original catalog date unknown; may include retired models. Active does not imply free.",
}
GROQ_FREE_MODELS = {
    "groq/llama-3.3-70b-versatile": {
        "name": "Llama 3.3 70B Versatile (Groq)",
        "context_length": 128000,
    },
    "groq/llama-3.1-8b-instant": {
        "name": "Llama 3.1 8B Instant (Groq)",
        "context_length": 128000,
    },
    "groq/gemma2-9b-it": {"name": "Gemma2 9B IT (Groq)", "context_length": 8192},
    "groq/mixtral-8x7b-32768": {"name": "Mixtral 8x7B (Groq)", "context_length": 32768},
}


def _is_free_price(value):
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def fetch_openrouter_free(timeout=15):
    """Fetches OpenRouter's model catalog, keeps the ones priced at zero.

    Returns (dict, None) on success, keyed by the raw OpenRouter id (no
    prefix; monitor.py normalizes ids). Returns (None, error_str) on
    failure so callers can tell "zero free models" from "fetch failed".
    """
    req = urllib.request.Request(
        OPENROUTER_MODELS_URL, headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeError, OSError) as e:
        return None, f"OpenRouter fetch error: {e}"

    try:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("expected data list")
        free = {}
        for m in payload["data"]:
            if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not m["id"]:
                raise ValueError("invalid model entry")
            pricing = m.get("pricing")
            if not isinstance(pricing, dict) or not {"prompt", "completion"} <= pricing.keys():
                raise ValueError("missing model pricing")
            for price in (pricing["prompt"], pricing["completion"]):
                if isinstance(price, bool) or not math.isfinite(float(price)) or float(price) < 0:
                    raise ValueError("invalid model pricing")
            context = m.get("context_length", 0) or 0
            if not isinstance(context, int) or isinstance(context, bool) or context < 0:
                raise ValueError("invalid context length")
            if _is_free_price(pricing["prompt"]) and _is_free_price(pricing["completion"]):
                free[m["id"]] = {
                    "name": m.get("name", m["id"]),
                    "context_length": m.get("context_length", 0) or 0,
                }
        return free, None
    except (TypeError, ValueError) as e:
        return None, f"OpenRouter catalog error: {e}"


def fetch_groq_free():
    """Compatibility API: legacy candidates, never proof of free eligibility."""
    return copy.deepcopy(GROQ_FREE_MODELS), None


for _info in GROQ_FREE_MODELS.values():
    _info.update({"source": "legacy_manual_candidates", "free_tier_verified": False,
                  "catalog_as_of": None, "reviewed_at": "2026-09-30"})


PROVIDERS = {
    "openrouter": fetch_openrouter_free,
    "groq": fetch_groq_free,
}

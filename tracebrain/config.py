import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

FALKOR_HOST = os.getenv("FALKOR_HOST", "localhost")
FALKOR_PORT = int(os.getenv("FALKOR_PORT", "6379"))


@dataclass(frozen=True)
class Provider:
    """An OpenAI-compatible endpoint. Model names differ per provider, so each carries its own."""
    name: str
    base_url: str
    api_key: str
    agent_model: str   # Triage / Investigator: strong tool calling
    fast_model: str    # cheap calls (entity-resolution fallback)


# Free tier only ($0 budget; Cerebras and Gemini were dropped as not free). Override any model in .env if a provider renames it.
PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        "groq", "https://api.groq.com/openai/v1", os.getenv("GROQ_API_KEY", ""),
        os.getenv("GROQ_AGENT_MODEL", "openai/gpt-oss-120b"),
        os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant"),
    ),
}

# Order to try. The first provider with a key is primary; on a long rate-limit wait we fall through.
LLM_PROVIDERS = [p.strip() for p in os.getenv("LLM_PROVIDERS", "groq").split(",") if p.strip()]
# A 429 asking us to wait longer than this (seconds) means "quota exhausted": switch provider.
LLM_MAX_WAIT_S = float(os.getenv("LLM_MAX_WAIT_S", "20"))
# Total time one call may spend waiting out short 429s on one provider before moving on.
LLM_RATE_WAIT_BUDGET_S = float(os.getenv("LLM_RATE_WAIT_BUDGET_S", "120"))
# Set to 0 to bypass the on-disk response cache (eval reruns are free with it on).
LLM_CACHE = os.getenv("TRACEBRAIN_LLM_CACHE", "1") == "1"

# Open-ended `valid_to` for temporal edges (2100-01-01), so hot queries never test for null.
FOREVER = 4102444800

# Default look-back window for suspect deploys.
DEFAULT_WINDOW_S = 24 * 3600

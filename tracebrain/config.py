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


# All free tiers ($0 budget). Override any model in .env if a provider renames it.
PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        "groq", "https://api.groq.com/openai/v1", os.getenv("GROQ_API_KEY", ""),
        os.getenv("GROQ_AGENT_MODEL", "openai/gpt-oss-120b"),
        os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant"),
    ),
    "cerebras": Provider(
        "cerebras", "https://api.cerebras.ai/v1", os.getenv("CEREBRAS_API_KEY", ""),
        os.getenv("CEREBRAS_AGENT_MODEL", "gpt-oss-120b"),
        os.getenv("CEREBRAS_FAST_MODEL", "gpt-oss-120b"),
    ),
    "gemini": Provider(
        "gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", os.getenv("GEMINI_API_KEY", ""),
        os.getenv("GEMINI_AGENT_MODEL", "gemini-flash-latest"),
        os.getenv("GEMINI_FAST_MODEL", "gemini-flash-lite-latest"),
    ),
}

# Order to try. The first provider with a key is primary; on a long rate-limit wait we fall through.
LLM_PROVIDERS = [p.strip() for p in os.getenv("LLM_PROVIDERS", "groq,cerebras,gemini").split(",") if p.strip()]
# A 429 asking us to wait longer than this (seconds) means "quota exhausted": switch provider.
LLM_MAX_WAIT_S = float(os.getenv("LLM_MAX_WAIT_S", "20"))
# Set to 0 to bypass the on-disk response cache (eval reruns are free with it on).
LLM_CACHE = os.getenv("TRACEBRAIN_LLM_CACHE", "1") == "1"

# Open-ended `valid_to` for temporal edges (2100-01-01), so hot queries never test for null.
FOREVER = 4102444800

# Default look-back window for suspect deploys.
DEFAULT_WINDOW_S = 24 * 3600

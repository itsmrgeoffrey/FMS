import json
import logging

from groq import AsyncGroq

from backend.config import settings

log = logging.getLogger(__name__)

_client: AsyncGroq | None = None


def get_client() -> AsyncGroq:
    """Construct the Groq client lazily so importing this module (e.g. in tests)
    doesn't require an API key — only generating a summary does."""
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


def reset_client() -> None:
    """Reset the LLM client (called when API key changes)."""
    global _client
    _client = None


async def generate_summary_text(system: str, user: str) -> str:
    """Call the configured LLM. If LLM_BASE_URL is set, use that OpenAI-compatible
    endpoint (e.g. a local Ollama) so transaction data never leaves the host;
    otherwise fall back to Groq. Raises on failure — the caller handles fallback."""
    if settings.llm_base_url:
        import httpx
        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.post(
                settings.llm_base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json={
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": 200,
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            return (resp.json()["choices"][0]["message"]["content"] or "").strip()

    response = await get_client().chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=200,
        temperature=0,
    )
    return (response.choices[0].message.content or "").strip()
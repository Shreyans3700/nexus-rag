"""Shared 'provider:model' fallback-chain parsing for ModelService/EmbeddingService."""
import os


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} must be configured")
    return value


def parse_provider_chain(env_var: str, default: str) -> list[tuple[str, str]]:
    """Parse a comma-separated ``provider:model`` list, e.g.

        "openai:gpt-4o-mini,anthropic:claude-3-5-haiku-20241022"

    into ``[("openai", "gpt-4o-mini"), ("anthropic", "claude-3-5-haiku-20241022")]``.
    The first entry is the primary model; the rest are tried in order as
    fallbacks if an earlier entry errors or is rate-limited.
    """
    raw = os.getenv(env_var, default)
    chain = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        provider, sep, model = entry.partition(":")
        if not sep or not provider.strip() or not model.strip():
            raise RuntimeError(
                f"{env_var} entries must look like 'provider:model' (got {entry!r})"
            )
        chain.append((provider.strip().lower(), model.strip()))
    if not chain:
        raise RuntimeError(f"{env_var} must define at least one 'provider:model' entry")
    return chain

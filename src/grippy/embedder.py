# SPDX-License-Identifier: MIT
"""Embedder factory — selects Agno embedder based on transport mode."""

from __future__ import annotations

from agno.knowledge.embedder.openai import OpenAIEmbedder


def create_embedder(
    transport: str,
    model: str,
    base_url: str,
    api_key: str = "lm-studio",
) -> OpenAIEmbedder:
    """Create an Agno embedder based on the resolved transport.

    Args:
        transport: "openai" or "local".
        model: Embedding model ID (e.g. "text-embedding-3-large").
        base_url: API base URL (used only for local transport).
        api_key: API key for non-OpenAI endpoints (default: "lm-studio").

    Returns:
        Configured OpenAIEmbedder instance.
    """
    if transport == "openai":
        return OpenAIEmbedder(id=model)
    if transport == "local":
        return OpenAIEmbedder(id=model, base_url=base_url, api_key=api_key)
    msg = f"Unknown transport: {transport!r}. Expected 'openai' or 'local'."
    raise ValueError(msg)

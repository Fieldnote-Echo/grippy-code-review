# SPDX-License-Identifier: MIT
"""Tests for Grippy embedder factory."""

from __future__ import annotations

from agno.knowledge.embedder.openai import OpenAIEmbedder


class TestCreateEmbedder:
    """create_embedder() returns the right Agno embedder for each transport."""

    def test_openai_transport_returns_openai_embedder(self) -> None:
        from grippy.embedder import create_embedder

        embedder = create_embedder(
            transport="openai",
            model="text-embedding-3-large",
            base_url="http://ignored",
        )
        assert isinstance(embedder, OpenAIEmbedder)
        assert embedder.id == "text-embedding-3-large"

    def test_local_transport_returns_embedder_with_base_url(self) -> None:
        from grippy.embedder import create_embedder

        embedder = create_embedder(
            transport="local",
            model="text-embedding-qwen3-embedding-4b",
            base_url="http://localhost:1234/v1",
        )
        assert isinstance(embedder, OpenAIEmbedder)
        assert embedder.id == "text-embedding-qwen3-embedding-4b"
        assert embedder.base_url == "http://localhost:1234/v1"

    def test_local_transport_uses_lm_studio_api_key(self) -> None:
        from grippy.embedder import create_embedder

        embedder = create_embedder(
            transport="local",
            model="test-model",
            base_url="http://localhost:1234/v1",
        )
        assert embedder.api_key == "lm-studio"

    def test_openai_transport_does_not_set_base_url(self) -> None:
        """OpenAI transport uses default base URL."""
        from grippy.embedder import create_embedder

        embedder = create_embedder(
            transport="openai",
            model="text-embedding-3-large",
            base_url="http://should-be-ignored",
        )
        assert embedder.base_url is None

    def test_unknown_transport_raises(self) -> None:
        """Unknown transport raises ValueError."""
        import pytest

        from grippy.embedder import create_embedder

        with pytest.raises(ValueError, match="Unknown transport"):
            create_embedder(transport="unknown", model="m", base_url="http://x")

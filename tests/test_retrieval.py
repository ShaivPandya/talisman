"""Retrieval routing and SQLite compatibility, without a model download."""

import sqlite3

import pytest

from api import retrieval


def test_postgres_search_does_not_attempt_embeddings(monkeypatch):
    monkeypatch.setattr(retrieval, "use_postgres_state", lambda: True)
    monkeypatch.setattr(retrieval, "_embed_single", lambda _: pytest.fail("embedding model was loaded"))
    calls = []

    def search(query, **kwargs):
        calls.append((query, kwargs))
        return [{"chunk_id": "match"}]

    monkeypatch.setattr(retrieval, "_pg_lexical_search", search)
    assert retrieval.search("growth", ["thesis"], ["nvda"], 3) == [{"chunk_id": "match"}]
    assert calls == [("growth", {"doc_types": ["thesis"], "tickers": ["nvda"], "top_k": 3})]


@pytest.mark.parametrize(("query", "top_k"), [("", 5), (" \n", 5), ("growth", 0), ("growth", -1)])
def test_empty_search_does_not_checkout(query, top_k, monkeypatch):
    monkeypatch.setattr(retrieval, "use_postgres_state", lambda: pytest.fail("empty search reached backend"))
    assert retrieval.search(query, top_k=top_k) == []


def test_sqlite_semantic_search_and_lexical_fallback_are_preserved(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    retrieval._init_db(conn)
    monkeypatch.setattr(retrieval, "_get_conn", lambda: conn)
    monkeypatch.setattr(retrieval, "use_postgres_state", lambda: False)
    monkeypatch.setattr(retrieval, "_embed", lambda texts: [[1.0, 0.0] for _ in texts])
    try:
        retrieval.index_document("thesis", "Semiconductor growth outlook", ticker="NVDA", doc_id="nvda")
        assert retrieval.search("growth")[0]["doc_id"] == "nvda"

        def unavailable(_):
            raise ImportError("test: model not installed")

        monkeypatch.setattr(retrieval, "_embed_single", unavailable)
        hit = retrieval.search("growth", tickers=["nvda"])[0]
        assert hit["doc_id"] == "nvda"
        assert hit["retrieval_mode"] == "lexical"
        assert hit["fallback_reason"] == "test: model not installed"
    finally:
        conn.close()

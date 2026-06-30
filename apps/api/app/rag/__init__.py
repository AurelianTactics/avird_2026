"""Narrative RAG (plan P2).

Retrieve relevant crash narratives for a question, assemble them into grounded
context with per-incident provenance, generate an answer that **cites the
incidents it used**, and self-check faithfulness — reusing the existing
``bge-base`` embedding cache. Local-first: P2 ships no public route; drive it via
``python -m app.rag.cli``.
"""

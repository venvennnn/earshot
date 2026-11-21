"""Retrieval over the enterprise knowledge base (knowledge/*.md): manuals, SOPs, asset histories, past cases.

Markdown is chunked at headings, embedded with the configured embedding model (OpenAI-compatible
embeddings endpoint, Gemini by default), and cached on disk. Retrieval is cosine top-k with sources.
If the embedding API is unavailable, a keyword-overlap retriever is used and the result says so.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from openai import AsyncOpenAI

from packs import KNOWLEDGE_DIR

log = logging.getLogger("earshot.rag")

_WORD = re.compile(r"[a-z0-9\-]+")


@dataclass(frozen=True)
class Chunk:
    source: str
    heading: str
    text: str


def chunk_markdown(source: str, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    title = ""
    heading = ""
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            chunks.append(Chunk(source, f"{title} / {heading}".strip(" /"), body))
        buf.clear()

    for line in text.splitlines():
        if line.startswith("# "):
            flush()
            title, heading = line[2:].strip(), ""
        elif line.startswith("## "):
            flush()
            heading = line[3:].strip()
        else:
            buf.append(line)
    flush()
    return chunks


class KnowledgeBase:
    def __init__(self, llm: AsyncOpenAI, embedding_model: str, cache_dir: Path) -> None:
        self._llm = llm
        self._model = embedding_model
        self._cache_dir = cache_dir
        self.chunks: list[Chunk] = []
        self._vectors: np.ndarray | None = None
        self.mode = "keyword"

    async def build(self, files: list[str]) -> None:
        self.chunks = []
        for name in files:
            path = KNOWLEDGE_DIR / name
            if path.exists():
                self.chunks.extend(chunk_markdown(name, path.read_text()))
        self._vectors = None
        self.mode = "keyword"
        if not self.chunks:
            return
        texts = [f"{c.heading}\n{c.text}" for c in self.chunks]
        digest = hashlib.sha256(json.dumps([self._model, texts]).encode()).hexdigest()[:16]
        cache = self._cache_dir / f"rag-{digest}.npy"
        try:
            if cache.exists():
                self._vectors = np.load(cache)
            else:
                self._vectors = await self._embed(texts)
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                np.save(cache, self._vectors)
            self.mode = "embeddings"
        except Exception as exc:  # embedding API unavailable: keep keyword retrieval
            log.warning("Embeddings unavailable (%s); using keyword retrieval", exc)
        log.info("Knowledge base: %d chunks from %d files (%s)", len(self.chunks), len(files), self.mode)

    async def _embed(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), 50):
            res = await self._llm.embeddings.create(model=self._model, input=texts[i : i + 50])
            vectors.extend(d.embedding for d in res.data)
        arr = np.asarray(vectors, dtype=np.float32)
        return arr / np.linalg.norm(arr, axis=1, keepdims=True)

    async def search(self, query: str, k: int = 4) -> list[dict[str, str | float]]:
        if not self.chunks:
            return []
        if self._vectors is not None:
            try:
                q = (await self._embed([query]))[0]
                scores = self._vectors @ q
            except Exception as exc:
                log.warning("Query embedding failed (%s); keyword fallback", exc)
                scores = self._keyword_scores(query)
        else:
            scores = self._keyword_scores(query)
        top = np.argsort(-scores)[:k]
        return [
            {"source": self.chunks[i].source, "section": self.chunks[i].heading, "text": self.chunks[i].text,
             "score": round(float(scores[i]), 3)}
            for i in top
            if scores[i] > 0
        ]

    def _keyword_scores(self, query: str) -> np.ndarray:
        q = set(_WORD.findall(query.lower()))
        return np.array(
            [len(q & set(_WORD.findall(f"{c.heading} {c.text}".lower()))) / (1 + len(q)) for c in self.chunks],
            dtype=np.float32,
        )

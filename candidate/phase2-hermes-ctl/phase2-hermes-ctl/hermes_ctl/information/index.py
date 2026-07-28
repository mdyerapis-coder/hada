"""Hermes CTL — Information subsystem (Phase 2).

Local, offline-capable information management: file indexing, a simple
inverted search index over indexed text, and a knowledge base that reuses the
MemoryStore knowledge graph. Stdlib-only; no network/secrets.

Real filesystem crawling is bounded (metadata + hashes only; file contents are
indexed by reference, not copied). Search is a minimal term-index — sufficient
for local verification and as the seam for a later semantic/vector search.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any

from hermes_ctl.memory.store import MemoryStore


@dataclass
class FileRecord:
    path: str
    size: int
    sha256: str
    mtime: float

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256, "mtime": self.mtime}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FileRecord":
        return cls(**d)


class FileIndex:
    """Index file metadata + content hashes under a root (read-only scan)."""

    _KEY = "information.files"

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def index_file(self, path: str) -> FileRecord:
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        size = os.path.getsize(path)
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        rec = FileRecord(path=path, size=size, sha256=h.hexdigest(), mtime=os.path.getmtime(path))
        files = self._all()
        files[path] = rec
        self._store.remember(self._KEY, [f.to_dict() for f in files.values()], tags=["information", "files"])
        return rec

    def get(self, path: str) -> FileRecord | None:
        return self._all().get(path)

    def all(self) -> list[FileRecord]:
        return list(self._all().values())

    def _all(self) -> dict[str, FileRecord]:
        try:
            raw = self._store.recall(self._KEY)
        except Exception:
            return {}
        return {d["path"]: FileRecord.from_dict(d) for d in raw}


class SearchIndex:
    """Minimal inverted term index over arbitrary named documents."""

    _KEY = "information.search"

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def index(self, doc_id: str, text: str) -> None:
        terms = self._tokenize(text)
        index = {k: set(v) for k, v in self._all().items()}
        for term in terms:
            index.setdefault(term, set()).add(doc_id)
        self._store.remember(self._KEY, {k: sorted(v) for k, v in index.items()}, tags=["information", "search"])

    def search(self, query: str) -> list[str]:
        index = self._all()
        results: set[str] = set()
        first = True
        for term in self._tokenize(query):
            hits = set(index.get(term, []))
            results = hits if first else (results & hits)
            first = False
        return sorted(results)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [t for t in text.lower().split() if t]

    def _all(self) -> dict[str, list[str]]:
        try:
            return dict(self._store.recall(self._KEY))
        except Exception:
            return {}


class KnowledgeBase:
    """Thin convenience over the MemoryStore knowledge graph."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def add_fact_node(self, node_id: str, kind: str, props: dict[str, Any] | None = None) -> Any:
        return self._store.add_node(node_id, kind, props)

    def link(self, source: str, relation: str, target: str) -> Any:
        return self._store.relate(source, relation, target)

    def related(self, node_id: str, relation: str | None = None) -> list[Any]:
        return self._store.neighbors(node_id, relation)

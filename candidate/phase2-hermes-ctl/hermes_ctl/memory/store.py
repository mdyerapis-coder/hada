"""Hermes CTL — Memory subsystem (Phase 2 foundation).

Dependency-light, context-free memory store providing three surfaces from
the Phase 2 roadmap:

  - Long-term memory: durable facts keyed by id, with tags + expiry.
  - Working memory: short-lived session-scoped scratch (no persistence).
  - Knowledge graph: typed nodes + edges for relationship modelling.

The store is intentionally stdlib-only (json + dataclasses) so it can run
inside the governed orchestrator without new runtime dependencies. Persistence
is pluggable: an in-memory backend (default) and a JSON-file backend.

Nothing here touches network, secrets, or infrastructure. It is pure data
modelling + verification-friendly logic.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Fact:
    """A single long-term memory fact."""

    id: str
    value: Any
    tags: set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def is_expired(self, now: float | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now if now is not None else time.time()) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "value": self.value,
            "tags": sorted(self.tags),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Fact":
        return cls(
            id=data["id"],
            value=data["value"],
            tags=set(data.get("tags", [])),
            created_at=data.get("created_at", time.time()),
            expires_at=data.get("expires_at"),
        )


@dataclass
class Node:
    """A knowledge-graph node."""

    id: str
    kind: str
    props: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "props": self.props}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Node":
        return cls(id=data["id"], kind=data["kind"], props=data.get("props", {}))


@dataclass
class Edge:
    """A directed, typed knowledge-graph edge."""

    source: str
    target: str
    relation: str

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "relation": self.relation}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Edge":
        return cls(source=data["source"], target=data["target"], relation=data["relation"])


class MemoryError(Exception):
    """Base error for memory operations."""


class MemoryStore:
    """Three-surface memory store with an optional JSON-file backend."""

    def __init__(self, persist_path: str | None = None) -> None:
        self._lock = threading.RLock()
        self._facts: dict[str, Fact] = {}
        self._working: dict[str, Any] = {}
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self._persist_path = persist_path
        if persist_path:
            self._load()

    # ---- long-term memory ----
    def remember(self, fact_id: str, value: Any, tags: Iterable[str] = (), ttl: float | None = None) -> Fact:
        with self._lock:
            fact = Fact(
                id=fact_id,
                value=value,
                tags=set(tags),
                expires_at=(time.time() + ttl) if ttl is not None else None,
            )
            self._facts[fact_id] = fact
            self._save()
            return fact

    def recall(self, fact_id: str, now: float | None = None) -> Any:
        with self._lock:
            fact = self._facts.get(fact_id)
            if fact is None:
                raise MemoryError(f"unknown fact: {fact_id}")
            if fact.is_expired(now):
                del self._facts[fact_id]
                self._save()
                raise MemoryError(f"fact expired: {fact_id}")
            return fact.value

    def forget(self, fact_id: str) -> None:
        with self._lock:
            if self._facts.pop(fact_id, None) is None:
                raise MemoryError(f"unknown fact: {fact_id}")
            self._save()

    def search(self, tag: str | None = None, now: float | None = None) -> list[Fact]:
        with self._lock:
            now = now if now is not None else time.time()
            out = []
            expired = []
            for fact in self._facts.values():
                if fact.is_expired(now):
                    expired.append(fact.id)
                    continue
                if tag is None or tag in fact.tags:
                    out.append(fact)
            for fid in expired:
                del self._facts[fid]
            if expired:
                self._save()
            return out

    # ---- working memory ----
    def put_working(self, key: str, value: Any) -> None:
        with self._lock:
            self._working[key] = value

    def get_working(self, key: str) -> Any:
        with self._lock:
            if key not in self._working:
                raise MemoryError(f"no working memory key: {key}")
            return self._working[key]

    def clear_working(self) -> None:
        with self._lock:
            self._working.clear()

    # ---- knowledge graph ----
    def add_node(self, node_id: str, kind: str, props: dict[str, Any] | None = None) -> Node:
        with self._lock:
            node = Node(id=node_id, kind=kind, props=props or {})
            self._nodes[node_id] = node
            self._save()
            return node

    def relate(self, source: str, relation: str, target: str) -> Edge:
        with self._lock:
            if source not in self._nodes:
                raise MemoryError(f"unknown source node: {source}")
            if target not in self._nodes:
                raise MemoryError(f"unknown target node: {target}")
            edge = Edge(source=source, target=target, relation=relation)
            self._edges.append(edge)
            self._save()
            return edge

    def set_relation(self, source: str, relation: str, target: str) -> Edge:
        """Set exactly one current edge for a source/target pair."""
        with self._lock:
            if source not in self._nodes:
                raise MemoryError(f"unknown source node: {source}")
            if target not in self._nodes:
                raise MemoryError(f"unknown target node: {target}")
            self._edges = [
                edge
                for edge in self._edges
                if not (edge.source == source and edge.target == target)
            ]
            edge = Edge(source=source, target=target, relation=relation)
            self._edges.append(edge)
            self._save()
            return edge

    def neighbors(self, node_id: str, relation: str | None = None) -> list[Edge]:
        with self._lock:
            return [
                e
                for e in self._edges
                if e.source == node_id and (relation is None or e.relation == relation)
            ]

    # ---- persistence ----
    def _save(self) -> None:
        if not self._persist_path:
            return
        snapshot = {
            "facts": [f.to_dict() for f in self._facts.values()],
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges],
        }
        tmp = self._persist_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2)
        __import__("os").replace(tmp, self._persist_path)

    def _load(self) -> None:
        import os

        if not os.path.exists(self._persist_path):  # type: ignore[arg-type]
            return
        with open(self._persist_path, "r", encoding="utf-8") as fh:  # type: ignore[arg-type]
            data = json.load(fh)
        for f in data.get("facts", []):
            self._facts[f["id"]] = Fact.from_dict(f)
        for n in data.get("nodes", []):
            self._nodes[n["id"]] = Node.from_dict(n)
        for e in data.get("edges", []):
            self._edges.append(Edge.from_dict(e))

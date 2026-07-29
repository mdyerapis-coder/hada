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

import fcntl
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator


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


class PersistenceCommitError(MemoryError):
    """The replacement is visible, but directory durability is uncertain."""

    committed = True


class MemoryStore:
    """Three-surface memory store with an optional JSON-file backend."""

    def __init__(self, persist_path: str | None = None) -> None:
        self._lock = threading.RLock()
        self._facts: dict[str, Fact] = {}
        self._working: dict[str, Any] = {}
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self._persist_path = persist_path
        self._transaction_depth = 0
        self._transaction_dirty = False
        self._transaction_error: BaseException | None = None
        self._transaction_snapshot: tuple[Any, ...] | None = None
        self._file_lock_handle: Any | None = None
        if persist_path:
            self._load()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Apply related mutations atomically in memory and on disk."""
        with self._lock:
            outermost = self._transaction_depth == 0
            if outermost:
                try:
                    self._acquire_file_lock()
                    if self._persist_path:
                        self._load()
                    self._transaction_snapshot = deepcopy(
                        (self._facts, self._working, self._nodes, self._edges)
                    )
                    self._transaction_dirty = False
                    self._transaction_error = None
                except BaseException:
                    self._release_file_lock()
                    raise
            self._transaction_depth += 1
            try:
                yield
            except BaseException as exc:
                self._transaction_depth -= 1
                if outermost:
                    self._restore_transaction_snapshot()
                else:
                    self._transaction_error = exc
                raise
            else:
                self._transaction_depth -= 1
                if outermost:
                    if self._transaction_error is not None:
                        error = self._transaction_error
                        self._restore_transaction_snapshot()
                        raise MemoryError(
                            f"transaction aborted after nested failure: {error}"
                        ) from error
                    try:
                        if self._transaction_dirty:
                            self._save()
                    except PersistenceCommitError:
                        # os.replace() already made the serialized transaction
                        # authoritative. Rolling live state back here would
                        # create a known live/durable contradiction.
                        self._transaction_snapshot = None
                        self._transaction_dirty = False
                        self._transaction_error = None
                        raise
                    except BaseException:
                        self._restore_transaction_snapshot()
                        raise
                    self._transaction_snapshot = None
                    self._transaction_dirty = False
            finally:
                if outermost:
                    self._release_file_lock()

    def _acquire_file_lock(self) -> None:
        if not self._persist_path:
            return
        handle = open(f"{self._persist_path}.lock", "a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except BaseException:
            handle.close()
            raise
        self._file_lock_handle = handle

    def _release_file_lock(self) -> None:
        handle = self._file_lock_handle
        self._file_lock_handle = None
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def _restore_transaction_snapshot(self) -> None:
        if self._transaction_snapshot is not None:
            self._facts, self._working, self._nodes, self._edges = (
                self._transaction_snapshot
            )
        self._transaction_snapshot = None
        self._transaction_dirty = False
        self._transaction_error = None
        self._transaction_depth = 0

    # ---- long-term memory ----
    def remember(self, fact_id: str, value: Any, tags: Iterable[str] = (), ttl: float | None = None) -> Fact:
        with self.transaction():
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
        expired = False
        value: Any = None
        with self.transaction():
            fact = self._facts.get(fact_id)
            if fact is None:
                raise MemoryError(f"unknown fact: {fact_id}")
            if fact.is_expired(now):
                del self._facts[fact_id]
                self._save()
                expired = True
            else:
                value = fact.value
        if expired:
            raise MemoryError(f"fact expired: {fact_id}")
        return value

    def recall_optional(self, fact_id: str, now: float | None = None) -> Any | None:
        """Return a fact value or ``None`` without raising for absence/expiry."""
        value: Any | None = None
        with self.transaction():
            fact = self._facts.get(fact_id)
            if fact is not None and fact.is_expired(now):
                del self._facts[fact_id]
                self._save()
            elif fact is not None:
                value = fact.value
        return value

    def has_fact(self, fact_id: str, now: float | None = None) -> bool:
        """Check presence without exceptions for normal control flow."""
        present = False
        with self.transaction():
            fact = self._facts.get(fact_id)
            if fact is not None and fact.is_expired(now):
                del self._facts[fact_id]
                self._save()
            else:
                present = fact is not None
        return present

    def forget(self, fact_id: str) -> None:
        with self.transaction():
            if self._facts.pop(fact_id, None) is None:
                raise MemoryError(f"unknown fact: {fact_id}")
            self._save()

    def search(self, tag: str | None = None, now: float | None = None) -> list[Fact]:
        with self.transaction():
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
        with self.transaction():
            node = Node(id=node_id, kind=kind, props=props or {})
            self._nodes[node_id] = node
            self._save()
            return node

    def relate(self, source: str, relation: str, target: str) -> Edge:
        with self.transaction():
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
        with self.transaction():
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

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and every connected edge as one durable mutation."""
        with self.transaction():
            removed = self._nodes.pop(node_id, None) is not None
            if removed:
                self._edges = [
                    edge
                    for edge in self._edges
                    if edge.source != node_id and edge.target != node_id
                ]
                self._save()
            return removed

    def neighbors(self, node_id: str, relation: str | None = None) -> list[Edge]:
        with self.transaction():
            return [
                e
                for e in self._edges
                if e.source == node_id and (relation is None or e.relation == relation)
            ]

    # ---- persistence ----
    def _save(self) -> None:
        if self._transaction_depth > 0:
            self._transaction_dirty = True
            return
        if not self._persist_path:
            return
        snapshot = {
            "facts": [f.to_dict() for f in self._facts.values()],
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges],
        }
        destination = os.path.abspath(self._persist_path)
        parent = os.path.dirname(destination) or "."
        tmp = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=parent,
                prefix=f"{os.path.basename(destination)}.tmp.",
                delete=False,
            ) as fh:
                tmp = fh.name
                json.dump(snapshot, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, destination)
            tmp = ""
            try:
                directory_fd = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError as exc:
                raise PersistenceCommitError(
                    "persistence replacement committed, but directory fsync failed; "
                    "live and durable state retain the committed transaction"
                ) from exc
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass

    def _load(self) -> None:
        if not os.path.exists(self._persist_path):  # type: ignore[arg-type]
            self._facts = {}
            self._nodes = {}
            self._edges = []
            return
        with open(self._persist_path, "r", encoding="utf-8") as fh:  # type: ignore[arg-type]
            data = json.load(fh)
        facts = {item["id"]: Fact.from_dict(item) for item in data.get("facts", [])}
        nodes = {item["id"]: Node.from_dict(item) for item in data.get("nodes", [])}
        edges = [Edge.from_dict(item) for item in data.get("edges", [])]
        self._facts = facts
        self._nodes = nodes
        self._edges = edges

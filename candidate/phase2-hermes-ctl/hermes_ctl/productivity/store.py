"""Hermes CTL — Productivity subsystem (Phase 2).

Calendar / Tasks / Notes / CRM foundations, all backed by MemoryStore so they
are durable, queryable, and offline-testable. Stdlib-only; no network/secrets.

These are data models + local query logic. Real calendar/CRM sync (Google
Calendar, external CRMs) is a later, gated integration that implements against
these stores' interfaces.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hermes_ctl.memory.store import MemoryStore


@dataclass
class Task:
    id: str
    title: str
    done: bool = False
    due: float | None = None
    priority: int = 3
    project: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "done": self.done,
            "due": self.due,
            "priority": self.priority,
            "project": self.project,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        return cls(**d)


@dataclass
class Note:
    id: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "tags": self.tags,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Note":
        return cls(**d)


@dataclass
class Event:
    id: str
    title: str
    start: float
    end: float
    attendees: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "attendees": self.attendees,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        return cls(**d)


@dataclass
class Entity:
    id: str
    name: str
    kind: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "kind": self.kind, "fields": self.fields}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Entity":
        return cls(**d)


class ProductivityStore:
    """Calendar / Tasks / Notes / CRM, persisted via MemoryStore."""

    _TASKS = "productivity.tasks"
    _NOTES = "productivity.notes"
    _EVENTS = "productivity.events"
    _ENTITIES = "productivity.crm"

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    # ---- tasks ----
    def add_task(self, task: Task) -> Task:
        items = self._list(self._TASKS, Task)
        items[task.id] = task
        self._save(self._TASKS, items)
        return task

    def list_tasks(self, *, only_open: bool = False) -> list[Task]:
        items = self._list(self._TASKS, Task)
        out = [t for t in items.values() if not (only_open and t.done)]
        return sorted(out, key=lambda t: (t.done, t.priority, t.due or 0))

    def complete_task(self, task_id: str) -> Task:
        items = self._list(self._TASKS, Task)
        if task_id not in items:
            raise KeyError(task_id)
        items[task_id].done = True
        self._save(self._TASKS, items)
        return items[task_id]

    # ---- notes ----
    def add_note(self, note: Note) -> Note:
        items = self._list(self._NOTES, Note)
        items[note.id] = note
        self._save(self._NOTES, items)
        return note

    def search_notes(self, tag: str | None = None) -> list[Note]:
        items = self._list(self._NOTES, Note)
        return [n for n in items.values() if tag is None or tag in n.tags]

    # ---- calendar ----
    def add_event(self, event: Event) -> Event:
        items = self._list(self._EVENTS, Event)
        items[event.id] = event
        self._save(self._EVENTS, items)
        return event

    def upcoming_events(self, now: float | None = None, *, within: float | None = None) -> list[Event]:
        now = now if now is not None else time.time()
        items = self._list(self._EVENTS, Event)
        out = [e for e in items.values() if e.end >= now and (within is None or e.start <= now + within)]
        return sorted(out, key=lambda e: e.start)

    # ---- crm ----
    def add_entity(self, entity: Entity) -> Entity:
        items = self._list(self._ENTITIES, Entity)
        items[entity.id] = entity
        self._save(self._ENTITIES, items)
        return entity

    def find_entity(self, name: str) -> Entity | None:
        items = self._list(self._ENTITIES, Entity)
        for e in items.values():
            if e.name.lower() == name.lower():
                return e
        return None

    # ---- internal ----
    def _list(self, key: str, cls):  # type: ignore[no-untyped-def]
        try:
            raw = self._store.recall(key)
        except Exception:
            return {}
        return {d["id"]: cls.from_dict(d) for d in raw}

    def _save(self, key: str, items: dict) -> None:  # type: ignore[no-untyped-def]
        self._store.remember(key, [v.to_dict() for v in items.values()], tags=["productivity"])

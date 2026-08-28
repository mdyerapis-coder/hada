# Schema — closed node types

The map uses a closed set of card types. Do not invent new types; if a noun does not fit, it is probably not a noun.

## Object card

Fields (from `_templates/object.md`):
1. One sentence — product name and code/file name if they differ
2. Why this shape — the load-bearing why
3. Shape — keys, constraints, or owning files, with citations
4. Connected to — owns / owned-by / joins / looks-like-but-is-not
5. If you change this — Hits / Does not hit (first-order only)
6. Surfaces — who reads/writes
7. See — the source file; at most one as-built page

## Process card

Fields (from `_templates/process.md`):
- Input → Movement → Output
- Numbered steps with citations
- consumes / produces as links to object cards
- Hits / Does not hit

## Universe markers

Every card carries `universe: live | leftover | ghost` in frontmatter.

## Status markers

Every object card carries `status: stub | verified | stale` in frontmatter. `verified` requires a date, a commit/branch, and citations.

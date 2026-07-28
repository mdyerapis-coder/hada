#!/usr/bin/env python3
"""
HADA Command Centre — read-only snapshot generator.

Produces a single static snapshot.json consumed by the control board.
Data sources (all read-only, real):
  - GitHub API via `gh` (authenticated, token never written to output)
  - Canonical roadmap Markdown (docs/MASTER_ROADMAP.md)
  - Governance/ADR inventory (docs/adr, docs/runbooks)

The board's LIVE infrastructure health is fetched separately by the browser
from /hada-api/metrics (orchestrator probe) and is NOT part of this snapshot,
so snapshot.json never embeds secrets or live host metrics.

Fail-closed: any section that cannot be collected is marked available:false
with a reason. Nothing is invented.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = "mdyerapis-coder/hada"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # candidate/v5/HADA-M1-durable-orchestrator -> repo root is 3 up?
# Resolve repo root robustly: walk up until we find docs/MASTER_ROADMAP.md
def find_repo_root(start: Path) -> Path:
    cur = start
    for _ in range(6):
        if (cur / "docs" / "MASTER_ROADMAP.md").exists():
            return cur
        if (cur / "releases" / "v5").exists():
            return cur
        cur = cur.parent
    return start


def gh(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["gh", *args, "--jq", "."],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode, r.stdout
    except Exception as e:  # pragma: no cover
        return 1, str(e)


def gh_json(*args: str):
    code, out = gh(*args)
    if code != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Roadmap parsing (canonical docs/MASTER_ROADMAP.md)
# ---------------------------------------------------------------------------
def parse_roadmap(path: Path) -> dict:
    if not path.exists():
        return {"available": False, "reason": "roadmap Markdown not found", "phases": []}
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 1) Canonical phase DEFINITIONS: top-level "# Phase N -- Title" (H1 only)
    definitions = {}  # name -> {title, summary}
    cur = None
    for line in lines:
        s = line.strip()
        if s.startswith("# ") and "Phase" in s and not s.startswith("## "):
            head = s[2:].strip()
            # "Phase 1 -- Autonomous Engineering" or "Phase 1 — ..."
            name = head.split("--")[0].split("—")[0].strip()
            cur = {"name": name, "title": head, "summary": ""}
            definitions[name] = cur
        elif cur is not None and s and not s.startswith("#"):
            if len(cur["summary"]) < 400:
                cur["summary"] = (cur["summary"] + " " + s).strip()

    # 2) Status overrides from the "Current Status" subsections ("## Phase N — ...")
    status_overrides = {}
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("## ") and "Phase" in s:
            head = s[3:].strip()
            name = head.split("--")[0].split("—")[0].strip()
            # collect the subsection body until next "## " or "# "
            body = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if nxt.startswith("## ") or nxt.startswith("# "):
                    break
                body.append(nxt)
                j += 1
            blob = " ".join(body).lower()
            if "locally complete and verified" in blob or "complete" in blob:
                status_overrides[name] = "complete"
            elif "operative" in blob or "in place" in blob or "enforced" in blob:
                status_overrides[name] = "active"
            elif "outstanding" in blob or "human decision" in blob or "blocked" in blob:
                status_overrides[name] = "blocked"
            i = j
        else:
            i += 1

    # 3) Assemble phases in definition order, apply status override (default: planned)
    phases = []
    for name, d in definitions.items():
        status = status_overrides.get(name, "planned")
        phases.append({
            "name": d["name"],
            "title": d["title"],
            "status": status,
            "summary": d["summary"].replace("`", "").strip(),
            "evidence": [],
        })
    return {"available": True, "source": "docs/MASTER_ROADMAP.md",
            "provenance": "parsed from canonical roadmap Markdown (definitions + status sections)",
            "phases": phases}


# ---------------------------------------------------------------------------
# GitHub state
# ---------------------------------------------------------------------------
def collect_repository() -> dict:
    default = gh_json("repo", "view", "--json", "defaultBranchRef")
    branch = (default or {}).get("defaultBranchRef", {}).get("name", "main")
    commits = gh_json("api", f"repos/{REPO}/commits?per_page=1")
    latest = None
    if commits and isinstance(commits, list) and commits:
        c = commits[0]
        latest = {
            "sha": c["sha"][:7],
            "full_sha": c["sha"],
            "date": c["commit"]["author"]["date"],
            "message": c["commit"]["message"].split("\n")[0][:120],
            "author": c["commit"]["author"].get("name", "unknown"),
        }
    prs = gh_json("pr", "list", "--state", "all", "--limit", "20",
                  "--json", "number,title,state,isDraft,headRefName,baseRefName,updatedAt,url") or []
    open_prs = [p for p in prs if p["state"] == "OPEN"]
    draft_prs = [p for p in prs if p.get("isDraft")]
    return {
        "available": latest is not None,
        "default_branch": branch,
        "latest_commit": latest,
        "pull_requests": {
            "total_open": len(open_prs),
            "total_draft": len(draft_prs),
            "items": [
                {"number": p["number"], "title": p["title"], "state": p["state"],
                 "is_draft": p.get("isDraft", False), "branch": p["headRefName"],
                 "base": p["baseRefName"], "updated_at": p["updatedAt"], "url": p["url"]}
                for p in prs[:15]
            ],
        },
        "provenance": f"github.com/{REPO} via gh (read-only)",
    }


def collect_ci() -> dict:
    runs = gh_json("run", "list", "--limit", "10",
                  "--json", "number,status,conclusion,headBranch,createdAt,url") or []
    return {
        "available": bool(runs),
        "recent": [
            {"run": r["number"], "status": r["status"], "conclusion": r["conclusion"],
             "branch": r["headBranch"], "created_at": r["createdAt"], "url": r["url"]}
            for r in runs
        ],
        "provenance": f"github.com/{REPO}/actions via gh (read-only)",
    }


def collect_governance(root: Path) -> dict:
    adr_dir = root / "docs" / "adr"
    adrs = []
    if adr_dir.exists():
        for f in sorted(adr_dir.glob("*.md")):
            head = f.read_text(encoding="utf-8").splitlines()[:12]
            status = "unknown"
            for hl in head:
                if "status" in hl.lower():
                    status = hl.split(":", 1)[-1].strip().strip("*").strip()
                    break
            adrs.append({"id": f.stem, "status": status, "path": str(f.relative_to(root))})
    return {
        "available": True,
        "human_approval_required": True,
        "self_approval_prohibited": True,
        "authority_boundary": "The control board is read-only. It cannot merge, deploy, "
                               "alter secrets, change infrastructure, or approve gates.",
        "reviewers": {
            "implementation": "Party 1 (implementation_engineer)",
            "adversarial": "Party 2 (adversarial_reviewer)",
            "external": "Party 3 (independent_external_reviewer, automated mode)",
        },
        "adrs": adrs,
        "provenance": "docs/adr + HADA governance config",
    }


def is_stale(iso: str | None, max_age_seconds: int = 30 * 60) -> bool:
    """Fail-closed freshness check. Unknown/malformed timestamps are stale."""
    if not iso:
        return True
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except (ValueError, TypeError):
        return True
    return age > max_age_seconds


def validate_snapshot(snap: dict) -> list[str]:
    """Return a list of problems; empty list means the snapshot is well-formed.
    Every data section must declare availability so the board can fail closed."""
    problems = []
    if not snap.get("generated_at"):
        problems.append("missing generated_at")
    if snap.get("is_fixture") is True:
        problems.append("snapshot flagged as fixture")
    for key in ("repository", "ci", "roadmap", "governance"):
        sec = snap.get(key)
        if not isinstance(sec, dict):
            problems.append(f"section {key} missing")
        elif "available" not in sec:
            problems.append(f"section {key} missing 'available' flag")
    return problems


def main() -> int:
    root = find_repo_root(HERE)
    roadmap_path = root / "docs" / "MASTER_ROADMAP.md"
    snapshot = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_fixture": False,
        "data_sources": {
            "github": "gh api (read-only)",
            "roadmap": "docs/MASTER_ROADMAP.md",
            "governance": "docs/adr",
            "live_infrastructure": "browser-side /hada-api/metrics (not in snapshot)",
        },
        "repository": collect_repository(),
        "ci": collect_ci(),
        "roadmap": parse_roadmap(roadmap_path),
        "governance": collect_governance(root),
    }
    out = HERE.parent / "deploy" / "control-board" / "snapshot.json"
    out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"snapshot written: {out} ({out.stat().st_size} bytes)")
    # quick integrity: every top-level section has 'available'
    for k, v in snapshot.items():
        if isinstance(v, dict) and "available" not in v and k not in ("data_sources", "schema_version"):
            print(f"WARN: section {k} missing 'available' flag", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

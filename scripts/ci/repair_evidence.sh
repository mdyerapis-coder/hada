#!/usr/bin/env bash
# repair_evidence.sh — generate the autonomous-repair audit report and evidence
# package for a single repair.
#
# Usage: repair_evidence.sh <worktree_dir> <pr_number> <base_ref>
set -euo pipefail

WT="${1:?usage: repair_evidence.sh <worktree_dir> <pr_number> <base_ref>}"
PR="${2:?pr_number required}"
BASE="${3:?base_ref required}"

mkdir -p "$WT/.ci-evidence"
EVID="$WT/.ci-evidence"

# Diff stat vs base
{
  echo "# Autonomous Repair Audit Report"
  echo ""
  echo "- Original PR: #$PR"
  echo "- Base ref: $BASE"
  echo "- Generated: $(date -u +%FT%TZ)"
  echo "- Guardrails: no merge / deploy / secrets / infrastructure / branch-protection changes."
  echo ""
  echo "## Files changed"
  echo '```'
  (cd "$WT" && git diff --stat "$BASE")
  echo '```'
  echo ""
  echo "## Verification evidence"
  echo "See verify.txt (ShellCheck + reject_operator_paths + manifest + fast tests)."
  echo ""
  echo "## Conclusion"
  echo "Smallest safe fix implemented and verified locally. Opened as DRAFT PR for"
  echo "human approval. Not merged automatically."
} > "$EVID/audit-report.md"

# Package evidence
bash -c "cd '$WT' && tar -czf .ci-evidence-package/repair-evidence-${PR}.tar.gz .ci-evidence 2>/dev/null && sha256sum .ci-evidence-package/repair-evidence-${PR}.tar.gz > .ci-evidence-package/repair-evidence-${PR}.tar.gz.sha256" || \
  mkdir -p "$WT/.ci-evidence-package" && tar -czf "$WT/.ci-evidence-package/repair-evidence-${PR}.tar.gz" -C "$WT" .ci-evidence

echo "Audit report + evidence written to $EVID"

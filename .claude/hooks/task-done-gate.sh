#!/usr/bin/env bash
# Stop hook: if the task left uncommitted or unpushed work, block the stop once
# and tell Claude to run the task-done workflow. The workflow ends with a clean,
# pushed tree, so the next stop passes. Quiet while the evidence review is pending (see below). stop_hook_active => never block twice.
[ -n "$REQUEST_LOG_HEADLESS" ] && exit 0  # inside the headless narrative run (headless-narrative.sh)
input=$(cat)
grep -q '"stop_hook_active":[[:space:]]*true' <<< "$input" && exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

dirty=$(git status --porcelain)
branch=$(python3 -c 'import json; g=json.load(open(".claude/project.json")).get("git",{}); print(g.get("remote","origin")+"/"+g.get("main_branch","main"))' 2>/dev/null || echo origin/main)
unpushed=$(git log --oneline "$branch"..HEAD 2>/dev/null)
[ -z "$dirty$unpushed" ] && exit 0

# Quiet while the current request's evidence review is running: the main agent marks the report's
# review section data-verdict="PENDING" when it launches the evidence-reviewer, and the reviewer
# replaces it with PASS or FAIL. A marker on a report untouched for 45 minutes no longer counts, so
# a crashed or forgotten review cannot silence this gate.
python3 - <<'PY' && exit 0
import re, sys, time
from pathlib import Path
best = ("", None)
for md in Path("requests_and_response").glob("*/request.md"):
    m = re.search(r"^- Started:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
    if m and m.group(1).strip() > best[0]:
        best = (m.group(1).strip(), md.parent / "report.html")
report = best[1]
if not report or not report.exists():
    sys.exit(1)
pending = re.search(r'<section id="review"[^>]*data-verdict="PENDING"', report.read_text(encoding="utf-8"))
sys.exit(0 if pending and time.time() - report.stat().st_mtime < 45 * 60 else 1)
PY

cat <<'EOF'
{"decision":"block","reason":"Uncommitted or unpushed work is left. If you completed a code task this turn, run the task-done workflow now (.claude/skills/task-done/SKILL.md): run the project checks and verify in Chrome, push to the main branch, verify the hosted preview if .claude/project.json enables one, fill the Task summary section of requests_and_response/<slug>/report.html. If this turn was only a question, or the user asked to skip the workflow, say so in one line and stop."}
EOF

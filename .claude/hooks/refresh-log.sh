#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit|Bash), runs with "async": true so it never delays the turn.
# Bookkeeping only (async hooks cannot block): after a write to a request's report.html it records
# the plan_ready timeline mark once (understanding, tasks and plan filled) and rebuilds; after a
# `git commit` it rebuilds so derived.js and the index show the new commit. The build writes only
# gitignored outputs (index.html, <slug>/derived.js, assets/), so it never dirties the work tree.
[ -n "$REQUEST_LOG_HEADLESS" ] && exit 0
input=$(cat)
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
python3 - "$input" <<'PY'
import json, re, subprocess, sys
from pathlib import Path
try:
    d = json.loads(sys.argv[1])
except ValueError:
    sys.exit(0)
tool, ti = d.get("tool_name", ""), d.get("tool_input") or {}
sys.path.insert(0, ".claude/skills/request-log")
if tool in ("Edit", "Write", "MultiEdit"):
    m = re.search(r"requests_and_response/([^/]+)/report\.html$", ti.get("file_path", ""))
    if not m:
        sys.exit(0)
    import timeline
    folder = Path("requests_and_response") / m.group(1)
    report = folder / "report.html"
    if timeline.status(report) != "done" and timeline.plan_filled(report) and \
            not any(e.get("kind") == "plan_ready" for e in timeline.events(folder)):
        timeline.append(folder, "plan_ready")
elif tool == "Bash":
    if not re.search(r"\bgit\b[^|;&]*\bcommit\b", ti.get("command", "")):
        sys.exit(0)
else:
    sys.exit(0)
subprocess.run([sys.executable, ".claude/skills/request-log/build_artifact.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
PY
exit 0

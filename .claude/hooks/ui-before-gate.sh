#!/usr/bin/env bash
# PreToolUse hook (Edit|Write|MultiEdit): before the first edit of a file that can change the UI,
# the current request must have its BEFORE screenshots (or a before/SKIP file saying why not).
# Exit 2 blocks the edit and shows the message to Claude.
[ -n "$REQUEST_LOG_HEADLESS" ] && exit 0  # inside the headless narrative run (headless-narrative.sh)
input=$(cat)
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

file=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("tool_input") or {}).get("file_path",""))' <<< "$input" 2>/dev/null)
[ -z "$file" ] && exit 0
rel=${file#"$PWD/"}

# Files that can change what the app shows: ui_paths minus ui_exclude in .claude/project.json
# (fnmatch patterns, where * also matches /).
python3 - "$rel" <<'PY' || exit 0
import fnmatch, json, sys
from pathlib import Path
rel = sys.argv[1]
try:
    cfg = json.loads(Path(".claude/project.json").read_text())
except (OSError, ValueError):
    cfg = {}
ui = cfg.get("ui_paths", ["src/*.jsx", "src/*.tsx", "src/*.js", "src/*.ts", "src/*.css", "index.html"])
skip = cfg.get("ui_exclude", [])
match = lambda pats: any(fnmatch.fnmatch(rel, p) for p in pats)
sys.exit(0 if match(ui) and not match(skip) else 1)
PY

slug=$(python3 - <<'EOF'
import re
from pathlib import Path
best = ("", "")
for md in Path("requests_and_response").glob("*/request.md"):
    m = re.search(r"^- Started:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
    if m and m.group(1).strip() > best[0]:
        best = (m.group(1).strip(), md.parent.name)
print(best[1])
EOF
)
[ -z "$slug" ] && exit 0
before="requests_and_response/$slug/before"
if [ -f "$before/SKIP" ] || ls "$before"/*.png >/dev/null 2>&1; then
  exit 0
fi

cat >&2 <<EOF
UI evidence gate: $rel can change the UI, and request "$slug" has no BEFORE screenshots yet.
Take them now, before any UI edit (the app must be running; see app.start in .claude/project.json):
  python3 .claude/skills/ui-evidence/capture_pages.py before
If this task really cannot change what the app shows, write the reason to $before/SKIP and retry.
EOF
exit 2

#!/usr/bin/env bash
# Stop hook: for the current request (requests_and_response/<slug>/), when it took BEFORE screenshots
# it must also have the AFTER capture; its report.html must show every changed view and every GIF;
# every GIF needs <name>-checks.json from record_flow.py with at least one check and no FAIL;
# and a report marked done must have its errors-and-prevention section, task summary, a PASS evidence
# review and suggested follow-ups filled in. Blocks once (stop_hook_active => never block twice).
[ -n "$REQUEST_LOG_HEADLESS" ] && exit 0  # inside the headless narrative run (headless-narrative.sh)
input=$(cat)
grep -q '"stop_hook_active":[[:space:]]*true' <<< "$input" && exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

reason=$(python3 - <<'PY'
import json, re, sys
from pathlib import Path
sys.path.insert(0, ".claude/skills/request-log")
from placeholders import has_placeholder
log = Path("requests_and_response")
best = ("", None)
for md in log.glob("*/request.md"):
    m = re.search(r"^- Started:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
    if m and m.group(1).strip() > best[0]:
        best = (m.group(1).strip(), md.parent)
folder = best[1]
if not folder:
    raise SystemExit
report = folder / "report.html"
html = report.read_text(encoding="utf-8") if report.exists() else ""
done = 'name="request-status" content="done"' in html

def section(sid):
    m = re.search(rf'<section id="{sid}"([^>]*)>(.*?)</section>', html, re.S)
    return (m.group(1), m.group(2)) if m else ("", "")

missing = []
if list((folder / "before").glob("*.png")):
    changes = folder / "ui-changes.json"
    if not changes.exists():
        missing.append("the AFTER capture (python3 .claude/skills/ui-evidence/capture_pages.py after)")
    else:
        for view in json.loads(changes.read_text())["changed"]:
            if f"ui-{view}.jpg" not in html:
                missing.append(f"the before/after image ui-{view}.jpg in {report}")
for gif in folder.glob("*.gif"):
    if gif.name not in html:
        missing.append(f"the GIF {gif.name} in {report}")
    checks = folder / f"{gif.stem}-checks.json"
    try:
        items = json.loads(checks.read_text())["checks"]
    except (OSError, ValueError, KeyError):
        items = None
    if not items:
        missing.append(f"named checks for the flow {gif.stem} ({checks.name} with at least one check; record it with record_flow.py and a run(page, base_url, check) flow)")
    elif any(c.get("result") != "PASS" for c in items):
        bad = ", ".join(c.get("name", "?") for c in items if c.get("result") != "PASS")
        missing.append(f"passing checks for the flow {gif.stem} (FAIL: {bad}) - fix the behaviour and record it again")
if done:
    _, body = section("task-summary")
    if not body or has_placeholder(body):
        missing.append(f"the Task summary section in {report} (task-done step 4)")
    _, body = section("errors")
    if not body or has_placeholder(body) or ("<td" not in body and "No errors" not in body):
        missing.append(f"the Errors and prevention section in {report} (a row per error, or 'No errors.')")
    _, body = section("follow-ups")
    if not body or has_placeholder(body) or "<li" not in body:
        missing.append(f"the Suggested follow-ups section in {report}")
    attrs, body = section("review")
    if 'data-verdict="PASS"' not in attrs or has_placeholder(body):
        missing.append(f"a PASS from the evidence-reviewer agent in the Evidence review section of {report}")
if missing:
    print(f"Request {folder.name} is missing: " + "; ".join(missing) + ".")
PY
)
[ -z "$reason" ] && exit 0
python3 -c 'import json,sys; print(json.dumps({"decision":"block","reason":sys.argv[1]+" Finish request-log step 6 and the ui-evidence steps (.claude/skills/request-log/SKILL.md, .claude/skills/ui-evidence/SKILL.md), or say in one line why they do not apply."}))' "$reason"

#!/usr/bin/env bash
# SubagentStart / SubagentStop hook, matcher "evidence-reviewer", "async": true.
#   start: records review_start on the current request's timeline.
#   stop:  records review_end with the verdict the reviewer wrote. If the report still says
#          data-verdict="PENDING", the reviewer ended without a verdict: the stale mark is cleared
#          (set to "") so task-done-gate stops treating the review as running. Then rebuilds.
[ -n "$REQUEST_LOG_HEADLESS" ] && exit 0
phase=$1
cat >/dev/null
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
python3 - "$phase" <<'PY'
import re, subprocess, sys
sys.path.insert(0, ".claude/skills/request-log")
import timeline
folder = timeline.current_folder()
if not folder:
    sys.exit(0)
report = folder / "report.html"
if sys.argv[1] == "start":
    timeline.append(folder, "review_start")
    sys.exit(0)
import time
def current():
    page = report.read_text(encoding="utf-8") if report.exists() else ""
    m = re.search(r'<section id="review" data-verdict="([A-Z]*)"', page)
    return page, (m.group(1) if m else "")
page, verdict = current()
if verdict == "PENDING":
    # SubagentStop can fire while the reviewer's last edit is still being written: wait, re-read, and
    # touch only the attribute of the fresh copy, never a page read before the reviewer finished
    time.sleep(15)
    page, verdict = current()
    if verdict == "PENDING":
        report.write_text(page.replace('<section id="review" data-verdict="PENDING"', '<section id="review" data-verdict=""', 1), encoding="utf-8")
        verdict = "none"
timeline.append(folder, "review_end", verdict=verdict or "none")
subprocess.run([sys.executable, ".claude/skills/request-log/build_artifact.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
PY
exit 0

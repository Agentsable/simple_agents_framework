#!/usr/bin/env bash
# Stop hook, "async": true. Opt-in: .claude/project.json "headless_narrative": {"enabled": true}.
# When the current request is not done, has saved check output in <slug>/checks/*.txt that is newer
# than the last narrative run, and its Execution summary is still unwritten, this starts a separate
# headless Claude Code run that drafts the Execution summary and Errors sections from that output,
# while the interactive session moves on. It edits only those two sections of report.html.
#   - claude -p --bare when ANTHROPIC_API_KEY is set (--bare reads no OAuth/keychain); otherwise
#     plain claude -p. REQUEST_LOG_HEADLESS=1 makes every hook in this repo skip itself in that run.
#   - one run at a time per request (<slug>/.narrative.lock); <slug>/.narrative.done remembers the
#     checks it was given, so the same output is never sent twice.
#   - model: headless_narrative.model (default haiku); command: headless_narrative.command (a list,
#     replaces "claude" - used by the tests) .
[ -n "$REQUEST_LOG_HEADLESS" ] && exit 0
cat >/dev/null
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
python3 - <<'PY'
import json, os, re, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, ".claude/skills/request-log")
import timeline
from placeholders import has_placeholder
try:
    cfg = (json.loads(Path(".claude/project.json").read_text()).get("headless_narrative") or {})
except (OSError, ValueError):
    cfg = {}
if not cfg.get("enabled"):
    sys.exit(0)
folder = timeline.current_folder()
if not folder:
    sys.exit(0)
report, checks = folder / "report.html", sorted((folder / "checks").glob("*.txt"))
if not report.exists() or not checks or timeline.status(report) == "done":
    sys.exit(0)
page = report.read_text(encoding="utf-8")
m = re.search(r'<section id="execution"[^>]*>(.*?)</section>', page, re.S)
body = m.group(1) if m else ""
written = len(re.sub(r"<[^>]+>|\s", "", body)) > 120 and not has_placeholder(body)
if written:
    sys.exit(0)
stamp = str(max(int(p.stat().st_mtime) for p in checks))
done_file, lock = folder / ".narrative.done", folder / ".narrative.lock"
if done_file.exists() and done_file.read_text().strip() == stamp:
    sys.exit(0)
if lock.exists() and time.time() - lock.stat().st_mtime < 1800:
    sys.exit(0)
lock.write_text(str(os.getpid()))
prompt = f"""You draft two sections of a request report. Work only on {report}.
Read {report} (the request, the understanding, the tasks and the plan) and every file in {folder}/checks/ (verbatim command output, one file per check).
1. Replace the inner HTML of <section id="execution"> with: <h2>Execution summary</h2>, a <ul> of what was done per plan step, <h3>Verification</h3> with one <li> per task saying which check proved it and its result, then each check's output verbatim in a <pre> (HTML-escaped), named after its file.
2. Replace the inner HTML of <section id="errors"> with <h2>Errors and prevention</h2> and, for every failure visible in the check output (non-zero exit, FAIL, error text), a row in <table class="errs rc"> with the columns #, What went wrong, Cause, Root cause (why-chain), How it was resolved, Prevention (start the prevention cell with <span class="prev suggested">suggested</span>). If the output shows no failure, write <p>No errors.</p>.
Rules: use only facts in those files, never invent a result; write braces as &#123;&#123; ; edit nothing else in the file."""
cmd = cfg.get("command") or ["claude"]
cmd = list(cmd) + ["-p", prompt, "--model", cfg.get("model", "haiku"), "--allowedTools", "Read,Edit", "--permission-mode", "acceptEdits"]
if os.environ.get("ANTHROPIC_API_KEY") and not cfg.get("command"):
    cmd.insert(1, "--bare")
env = {**os.environ, "REQUEST_LOG_HEADLESS": "1"}
try:
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=900)
    (folder / ".narrative.log").write_text(f"exit {r.returncode}\n{r.stdout[-4000:]}\n{r.stderr[-4000:]}")
    if r.returncode == 0:
        done_file.write_text(stamp)
        timeline.append(folder, "narrative", checks=len(checks))
finally:
    lock.unlink(missing_ok=True)
subprocess.run([sys.executable, ".claude/skills/request-log/build_artifact.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
PY
exit 0

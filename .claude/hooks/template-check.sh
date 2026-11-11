#!/usr/bin/env bash
# SessionStart hook: one line when the template repo has a newer commit than the one this project's
# .claude/ was last updated to (.claude/template-lock.json), so the update is not forgotten.
# Silent when up to date, in the template repo itself, and when the template cannot be reached
# within a few seconds (offline): a session start must never wait on the network.
cat >/dev/null
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
python3 - <<'PY' 2>/dev/null
import json, re, subprocess
from pathlib import Path

def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

def norm(url):
    return re.sub(r"(\.git)?/*$", "", url.strip().lower())

cfg = read(".claude/project.json").get("template") or {}
repo, branch = cfg.get("repo"), cfg.get("branch", "main")
if not repo:
    raise SystemExit
remote = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True).stdout
if remote and norm(remote) == norm(repo):
    raise SystemExit  # this is the template repo itself
lock = read(".claude/template-lock.json")
# Not in the projects directory yet (no row ever written from this machine): ask for the sign-up.
reg_script = Path(".claude/skills/projects-directory/register_project.py")
if reg_script.is_file():
    import os
    registry = Path(os.environ.get("TEMPLATE_PROJECTS_REGISTRY", "~/.claude/template-projects.json")).expanduser()
    try:
        out = subprocess.run(["python3", str(reg_script), "--project", ".", "--dry-run"], capture_output=True,
                             text=True, timeout=5)
        doc_id = json.loads(out.stdout)["doc_id"]
    except Exception:
        doc_id = None
    if doc_id and doc_id not in (read(registry).get("projects") or {}):
        dirty = subprocess.run(["git", "status", "--porcelain", "--", ".claude", ".gitignore"],
                               capture_output=True, text=True).stdout.strip()
        print("Template: this project uses the .claude template but is not in the Template Projects directory yet. "
              "Before the user's first request, sign it up: "
              + ("first commit only the template files (git add .claude .gitignore; message "
                 "'chore: add the .claude template'; push if the branch is level with its remote), then " if dirty else "")
              + "follow .claude/skills/projects-directory/SKILL.md (run register_project.py, write the row with "
              "ArtifactData). Fill app.start / app.base_url in .claude/project.json if they are null. "
              "Tell the user it was registered.")
if not lock.get("commit"):
    print("Template: this project's .claude/ has no template-lock.json yet, so it cannot tell whether "
          "the template has changed. Say 'update the template' once to record its version.")
    raise SystemExit
try:
    out = subprocess.run(["git", "ls-remote", repo, f"refs/heads/{branch}"], capture_output=True, text=True,
                         timeout=4, env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})
except subprocess.TimeoutExpired:
    raise SystemExit
latest = out.stdout.split()[0] if out.returncode == 0 and out.stdout.strip() else ""
if latest and latest != lock["commit"]:
    print(f"Template: a newer version of the template is available ({latest[:7]}; this project's .claude/ "
          f"is at {lock['commit'][:7]}). Tell the user, and offer to 'update the template' (/update-template).")
PY
exit 0

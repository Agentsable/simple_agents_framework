#!/usr/bin/env bash
# PreToolUse hook (Edit|Write|MultiEdit|NotebookEdit and Bash): no change to a project file until the
# current request's report.html has its understanding, tasks and plan filled in (request-log steps 2-4).
# Not gated: the request log itself (requests_and_response/), which is where the plan is written,
# and files outside the project (scratchpad, memory).
# Bash: the command is scanned for writes - redirects (> >>), tee, sed -i, cp/mv/rm/touch/install,
# and Python write_text/write_bytes/open(..., "w"|"a")/unlink on a path literal or a variable set
# from Path("...") - following `cd` in the command. A best-effort check: a command that builds its
# target path at run time is not seen.
# Exit 2 blocks the call and shows the message to Claude.
[ -n "$REQUEST_LOG_HEADLESS" ] && exit 0  # inside the headless narrative run (headless-narrative.sh)
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
HOOK_INPUT=$(cat) python3 - <<'PY'
import json, os, re, shlex, sys
from pathlib import Path

root = Path.cwd().resolve()
try:
    data = json.loads(os.environ.get("HOOK_INPUT") or "{}")
except ValueError:
    sys.exit(0)
tool = data.get("tool_name") or ""
inp = data.get("tool_input") or {}
start = Path(data.get("cwd") or root)


def in_project(path: Path):
    """Project-relative path of a file this gate protects, else None."""
    try:
        rel = path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None  # outside the project
    if rel.startswith("requests_and_response/") or rel.startswith(".git/"):
        return None
    return rel


WRITE_CMDS = {"tee", "cp", "mv", "rm", "touch", "install", "ln", "truncate", "rsync"}
PY_WRITE = re.compile(r"\.(write_text|write_bytes|unlink|rename|replace|touch|mkdir)\(|open\([^)]*['\"][wax]\+?b?['\"]|shutil\.|os\.(remove|unlink|rename)")


def bash_targets(command: str) -> list[str]:
    targets, cwd, var_paths = [], start, {}
    heredoc = None  # end marker while inside a heredoc body
    for line in command.splitlines():
        if heredoc is not None:
            if line.strip() == heredoc:
                heredoc = None
                continue
            for name, _, lit in re.findall(r"(\w+)\s*=\s*Path\(\s*(['\"])(.+?)\2\s*\)", line):
                var_paths[name] = cwd / lit
            if PY_WRITE.search(line):
                for lit in re.findall(r"Path\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\.\s*(?:write|unlink|touch|mkdir|rename|replace)", line):
                    targets.append(cwd / lit)
                for lit in re.findall(r"open\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][wax]", line):
                    targets.append(cwd / lit)
                for name in re.findall(r"\b(\w+)\.(?:write_text|write_bytes|unlink|touch|rename|replace)\(", line):
                    if name in var_paths:
                        targets.append(var_paths[name])
            continue
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        if m:
            heredoc = m.group(1)
            line = line[:m.start()]
        for seg in re.split(r"&&|\|\||;|\|", line):
            seg = seg.strip()
            if not seg:
                continue
            for redir in re.findall(r"(?:^|[^0-9&<>])>>?\s*([^\s&|;<>]+)", seg):
                if redir not in ("/dev/null", "/dev/stderr", "/dev/stdout") and not redir.startswith("&"):
                    targets.append(cwd / redir.strip("'\""))
            try:
                words = shlex.split(re.sub(r"\d*>>?\s*[^\s&|;<>]+", " ", seg))
            except ValueError:
                words = seg.split()
            while words and re.match(r"^\w+=", words[0]):
                words = words[1:]  # VAR=value prefixes
            if not words:
                continue
            cmd = os.path.basename(words[0])
            args = [w for w in words[1:] if w and not w.startswith("-")]  # '' is sed -i's macOS suffix
            if cmd == "cd" and args:
                cwd = (cwd / os.path.expanduser(args[0]))
            elif cmd in ("tee", "rm", "touch", "truncate"):
                targets += [cwd / a for a in args]
            elif cmd in ("cp", "mv", "install", "ln", "rsync") and len(args) >= 2:
                targets.append(cwd / args[-1])
                if cmd == "mv":
                    targets += [cwd / a for a in args[:-1]]
            elif cmd == "sed" and re.search(r"\s-i", seg) and args:
                targets += [cwd / a for a in args[1:]]
            elif cmd in ("perl",) and re.search(r"\s-\w*i", seg) and args:
                targets += [cwd / a for a in args[1:]]
            elif cmd.startswith("python") and "-c" in words and PY_WRITE.search(seg):
                targets += [cwd / lit for lit in re.findall(r"['\"]([\w./-]+\.\w+)['\"]", seg)]
    return [rel for t in targets if (rel := in_project(t))]


if tool == "Bash":
    protected = bash_targets(inp.get("command") or "")
    if not protected:
        sys.exit(0)
    what = f"this command writes {', '.join(sorted(set(protected))[:3])}"
else:
    file = inp.get("file_path") or inp.get("notebook_path") or ""
    if not file:
        sys.exit(0)
    rel = in_project(Path(os.path.abspath(os.path.join(root, file))))
    if rel is None:
        sys.exit(0)
    what = f"{rel} cannot be edited"

sys.path.insert(0, ".claude/skills/request-log")
from placeholders import has_placeholder

best = ("", None)
for md in Path("requests_and_response").glob("*/request.md"):
    m = re.search(r"^- Started:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
    if m and m.group(1).strip() > best[0]:
        best = (m.group(1).strip(), md.parent)
folder = best[1]
if folder is None:
    print(f"Plan gate: no request is logged yet, so {what}. Save the request first "
          "(request-log step 1: requests_and_response/<slug>/request.md).", file=sys.stderr)
    sys.exit(2)
report = folder / "report.html"
html = report.read_text(encoding="utf-8") if report.exists() else ""
missing = []
for sid, label in (("understood", "What I understood"), ("tasks", "Tasks and verification"), ("plan", "Implementation plan")):
    m = re.search(rf'<section id="{sid}"[^>]*>(.*?)</section>', html, re.S)
    if not m or has_placeholder(m.group(1)) or len(re.sub(r"<[^>]+>|\s", "", m.group(1))) < 40:
        missing.append(label)
if missing:
    print(f"Plan gate: request \"{folder.name}\" has no {', '.join(missing)} in {report} yet, so {what}. "
          "Write those sections first (request-log steps 2-4, publish the artifact), then retry.", file=sys.stderr)
    sys.exit(2)
PY

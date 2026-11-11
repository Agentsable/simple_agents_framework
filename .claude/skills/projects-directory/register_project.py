#!/usr/bin/env python3
"""The projects directory row for this project (every project that uses the template).

    register_project.py                  # print the row as JSON, bumping the version on a new push
    register_project.py --project <dir>  # for another project folder
    register_project.py --dry-run        # print the row without recording anything

Version numbers: the first registration of a project records the commit on its remote branch
(<git.remote>/<git.main_branch>, the last pushed version) as version 1. Each later registration whose
pushed commit differs from the last one recorded adds 1. They are kept in a machine-wide registry,
~/.claude/template-projects.json (or $TEMPLATE_PROJECTS_REGISTRY), never in the project, so
recording a version never needs a commit of its own.

Output: {"collection": "projects", "doc_id": ..., "data": {...}, "directory_url": ...}. Claude writes
"data" to the directory artifact's database with ArtifactData set (see SKILL.md): a script cannot
write to an artifact, Claude can.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = Path(os.environ.get("TEMPLATE_PROJECTS_REGISTRY", "~/.claude/template-projects.json")).expanduser()


def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def web_url(remote: str) -> str:
    """https URL of a git remote (scp-style and ssh URLs too), without .git."""
    remote = remote.strip()
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    return re.sub(r"\.git/?$", "", re.sub(r"^(https?://)[^@/]+@", r"\1", remote))


def as_list(value) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [str(v).strip() for v in items if isinstance(v, str) and re.match(r"https?://\S+", v.strip())]


def row(root: Path) -> dict:
    cfg = read_json(root / ".claude" / "project.json")
    app, gcfg = cfg.get("app") or {}, cfg.get("git") or {}
    remote_name, branch = gcfg.get("remote", "origin"), gcfg.get("main_branch", "main")
    remote = git(root, "remote", "get-url", remote_name)
    repo = web_url(remote) if remote else ""
    name = str(cfg.get("project_name") or "").strip() or (repo.rstrip("/").rsplit("/", 1)[-1] if repo else root.name)
    # the last pushed version: the remote-tracking branch (updated by every push and fetch)
    commit = git(root, "rev-parse", f"{remote_name}/{branch}") or git(root, "rev-parse", "HEAD")
    pushed = bool(git(root, "rev-parse", f"{remote_name}/{branch}"))
    date = git(root, "show", "-s", "--format=%cI", commit) if commit else ""
    start = app.get("start") or "./start.sh"
    start_path = (root / start).resolve() if start.startswith((".", "/")) or "/" not in start else None
    has_start = bool(start_path and start_path.is_file())
    looks_script = start.startswith(("./", "/")) or start.endswith(".sh")
    lock = read_json(root / ".claude" / "template-lock.json")
    template_repo = (cfg.get("template") or {}).get("repo", "")
    doc_id = re.sub(r"[^a-z0-9-]+", "-", (repo.split("://", 1)[-1].split("/", 1)[-1] if repo else root.name).lower()).strip("-")
    return {
        "doc_id": doc_id or "project",
        "name": name,
        "git": repo,
        "branch": branch,
        "folder": str(root),
        "request_log": (read_json(root / ".claude" / "skills" / "request-log" / "artifact.json").get("url") or ""),
        "commit": commit,
        "commit_url": f"{repo}/commit/{commit}" if repo.startswith("https://github.com/") and commit else "",
        "pushed": pushed,
        "pushed_at": date,
        "start_sh": str(start_path) if has_start else "",
        # a script that exists, or a plain command (bun run dev); never a script path that is missing
        "start_cmd": f'cd "{root}" && {start}' if has_start or (app.get("start") and not looks_script) else "",
        "local_urls": as_list(app.get("base_url")) + [u for u in as_list(app.get("local_urls")) if u not in as_list(app.get("base_url"))],
        "deployed_urls": as_list(app.get("deployed_url")) + as_list(app.get("deployed_urls")),
        "template_commit": lock.get("commit", ""),
        "is_template": bool(remote) and web_url(template_repo) == repo,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", help="project folder (default: the project this script is in)")
    ap.add_argument("--dry-run", action="store_true", help="do not record the version")
    args = ap.parse_args()
    root = Path(args.project).expanduser().resolve() if args.project else HERE.parents[2]
    if not (root / ".claude").is_dir():
        sys.exit(f"{root} has no .claude folder: it does not use the template.")
    r = row(root)
    doc_id = r.pop("doc_id")

    registry = read_json(REGISTRY) or {"projects": {}}
    entry = registry["projects"].setdefault(doc_id, {"versions": []})
    versions = entry["versions"]
    if r["commit"] and (not versions or versions[-1]["commit"] != r["commit"]):
        versions.append({"version": len(versions) + 1, "commit": r["commit"], "pushed_at": r["pushed_at"],
                         "recorded": datetime.now().astimezone().isoformat(timespec="seconds")})
    entry.update(folder=r["folder"], name=r["name"])
    r["version"] = versions[-1]["version"] if versions else 0
    r["versions"] = len(versions)
    r["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    if not args.dry_run:
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    directory = read_json(HERE / "directory.json").get("url") or ""
    json.dump({"collection": "projects", "doc_id": doc_id, "data": r, "directory_url": directory},
              sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()

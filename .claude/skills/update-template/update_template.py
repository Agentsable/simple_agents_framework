#!/usr/bin/env python3
"""Update this project's .claude/ folder from the template repo, without losing local work.

    update_template.py            # dry run: fetch the template and print what would change
    update_template.py --apply    # write the changes and record them in .claude/template-lock.json

Options: --repo <git url or path> and --branch <name> (default: template.repo / template.branch in
.claude/project.json), --project <dir> (the project to update, default: the one this script is in;
run the template's own copy with --project to update a project that has no update-template skill
yet, or to install the template into a new folder), --force (apply even if .claude/ has uncommitted
changes or the project is not a git repo).

What it does with each file:
  same       the project's copy already equals the template's                      -> nothing
  add        new in the template, not in the project                               -> written
  update     the project's copy equals an earlier template version (never edited)   -> replaced
  merge      edited locally AND changed in the template, on different lines         -> 3-way merged
  conflict   edited locally AND changed in the template, on the same lines          -> local kept,
             the template's version written next to it as <file>.template
  keep       edited locally, the template did not change it since                   -> nothing
  delete     removed from the template, the project's copy was never edited         -> deleted
  orphan     removed from the template, but edited locally                          -> kept
  config     project-owned settings file (template.project_owned)                   -> only keys the
             template added are filled in (project.json); other owned files are only added if missing
Files that exist only in the project are never touched. The merge base for an edited file is the
template version recorded in template-lock.json by the last update; without a lock (the first run)
it is the template version closest to the project's copy.
"""
import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CLAUDE = ".claude"
LOCK = ".claude/template-lock.json"
DEFAULT_REPO = "https://github.com/spiceroutes/claude_template_request_tasks_and_evidance_html.git"
DEFAULT_OWNED = [".claude/project.json", ".claude/skills/request-log/artifact.json",
                 ".claude/skills/ui-evidence/pages.json"]
NEVER = {LOCK, ".claude/settings.local.json"}  # per-project files, never taken from the template


def run(*args, cwd=None, check=True, data=None) -> subprocess.CompletedProcess:
    out = subprocess.run(args, cwd=cwd, input=data, capture_output=True)
    if check and out.returncode != 0:
        sys.exit(f"{' '.join(map(str, args))} failed: {out.stderr.decode(errors='replace').strip()}")
    return out


def blob_id(data: bytes) -> str:
    """The git blob id of some content, so local files compare with template history without git."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def merge_keys(local, template):
    """Fill in keys the template has and the project lacks; keep every local value. _comment keys
    describe the template's settings, so they follow the template."""
    if not isinstance(local, dict) or not isinstance(template, dict):
        return local
    out = dict(local)
    for key, value in template.items():
        if key not in out or key.startswith("_comment"):
            out[key] = value
        else:
            out[key] = merge_keys(out[key], value)
    return out


class Template:
    def __init__(self, repo: str, branch: str):
        self.dir = Path(tempfile.mkdtemp(prefix="claude-template-"))
        run("git", "clone", "--quiet", "--no-checkout", "--branch", branch, repo, str(self.dir))
        self.commit = self.git("rev-parse", "HEAD").strip()
        self.files = {}  # path -> (mode, blob) at HEAD
        for line in self.git("ls-tree", "-r", "HEAD", "--", CLAUDE).splitlines():
            meta, path = line.split("\t", 1)
            mode, _, blob = meta.split()
            if path not in NEVER and not path.endswith(".template"):
                self.files[path] = (mode, blob)
        self.history = {}  # path -> [blob, ...] every version it ever had, newest first
        log = self.git("log", "--format=", "--raw", "--no-abbrev", "--no-renames", "HEAD", "--", CLAUDE)
        for line in log.splitlines():
            if not line.startswith(":"):
                continue
            meta, path = line.split("\t", 1)
            new = meta.split()[3]
            if set(new) != {"0"}:
                self.history.setdefault(path, [])
                if new not in self.history[path]:
                    self.history[path].append(new)

    def git(self, *args) -> str:
        return run("git", *args, cwd=self.dir).stdout.decode()

    def blob(self, blob: str) -> bytes:
        return run("git", "cat-file", "blob", blob, cwd=self.dir).stdout

    def blob_at(self, commit: str, path: str):
        out = run("git", "rev-parse", "--verify", "--quiet", f"{commit}:{path}", cwd=self.dir, check=False)
        return out.stdout.decode().strip() if out.returncode == 0 else None

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def closest(tpl: Template, path: str, local: bytes):
    """The template version of path most like the project's copy (merge base when there is no lock)."""
    best, score = None, -1.0
    text = local.decode("utf-8", errors="replace").splitlines()
    for blob in tpl.history.get(path, []):
        ratio = difflib.SequenceMatcher(None, tpl.blob(blob).decode("utf-8", errors="replace").splitlines(), text).ratio()
        if ratio > score:
            best, score = blob, ratio
    return best


def merge3(local: bytes, base: bytes, new: bytes):
    """git merge-file: (merged bytes, clean?)."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name, data in (("local", local), ("base", base), ("new", new)):
            p = Path(tmp) / name
            p.write_bytes(data)
            paths.append(str(p))
        out = run("git", "merge-file", "-p", "-L", "project", "-L", "installed", "-L", "template", *paths, check=False)
        if out.returncode < 0 or out.returncode > 127:
            return None, False  # binary or error
        return out.stdout, out.returncode == 0


def plan(tpl: Template, lock: dict, owned: set) -> list[dict]:
    actions = []
    base_commit = lock.get("commit")
    if base_commit and run("git", "cat-file", "-e", f"{base_commit}^{{commit}}", cwd=tpl.dir, check=False).returncode:
        base_commit = None  # the lock names a commit the template no longer has (force-push): fall back
    installed = set(lock.get("files", []))
    for path, (mode, blob) in sorted(tpl.files.items()):
        new = tpl.blob(blob)
        target = ROOT / path
        a = {"path": path, "mode": mode, "new": new}
        if path in owned:
            if not target.exists():
                fresh = fresh_owned(path, new)
                actions.append(dict(a, kind="add", data=fresh, why="project-owned file, missing here"
                                    + (" (this project's own values, not the template's)" if fresh != new else "")))
            elif path.endswith(".json") and Path(path).name == "project.json":
                local_cfg = read_json(target)
                merged = merge_keys(local_cfg, json.loads(new or b"{}"))
                if merged != local_cfg:
                    added = sorted(k for k in flat_keys(merged) if k not in flat_keys(local_cfg))
                    a["data"] = (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode()
                    actions.append(dict(a, kind="config", why="new keys: " + (", ".join(added) or "comments only")))
                else:
                    actions.append(dict(a, kind="same", why="project-owned, no new keys"))
            else:
                actions.append(dict(a, kind="same", why="project-owned, kept as is"))
            continue
        if not target.exists():
            if path in installed:
                actions.append(dict(a, kind="keep", why="removed in this project after an earlier update"))
            else:
                actions.append(dict(a, kind="add", why="new in the template"))
            continue
        local = target.read_bytes()
        local_id = blob_id(local)
        if local_id == blob:
            actions.append(dict(a, kind="same", why="")); continue
        if local_id in tpl.history.get(path, []):
            actions.append(dict(a, kind="update", why="not edited here since an earlier template version")); continue
        base_blob = tpl.blob_at(base_commit, path) if base_commit else None
        how = "version from the last update"
        if not base_blob:
            base_blob, how = closest(tpl, path, local), "closest template version (no lock yet)"
        if base_blob == blob:
            actions.append(dict(a, kind="keep", why="edited here; the template has not changed it since")); continue
        if not base_blob:
            actions.append(dict(a, kind="conflict", why="edited here and no earlier template version to merge from")); continue
        merged, clean = merge3(local, tpl.blob(base_blob), new)
        if clean:
            actions.append(dict(a, kind="merge", data=merged, why=f"edited here and in the template; merged from the {how}"))
        else:
            actions.append(dict(a, kind="conflict", why=f"edited here and in the template on the same lines (base: {how})"))
    # files the template removed
    for path, versions in sorted(tpl.history.items()):
        target = ROOT / path
        if path in tpl.files or path in NEVER or path in owned or not target.is_file():
            continue
        if blob_id(target.read_bytes()) in versions:
            actions.append({"path": path, "kind": "delete", "why": "removed from the template, not edited here"})
        else:
            actions.append({"path": path, "kind": "orphan", "why": "removed from the template, but edited here: kept"})
    return actions


def detect_app(root: Path) -> tuple[dict, list]:
    """This project's start command, local address and checks, guessed from its own files, for a
    project.json written on a fresh install (the template's values describe the template, not it)."""
    import re
    pkg = read_json(root / "package.json")
    scripts = pkg.get("scripts") or {}
    pm = next((m for f, m in (("bun.lock", "bun"), ("bun.lockb", "bun"), ("pnpm-lock.yaml", "pnpm"),
                              ("yarn.lock", "yarn")) if (root / f).exists()), "npm")
    start = "./start.sh" if (root / "start.sh").is_file() else (f"{pm} run dev" if "dev" in scripts
                                                              else f"{pm} start" if "start" in scripts else None)
    base = None
    for name in ["start.sh", "package.json", ".env", ".env.local", *sorted(p.name for p in root.glob("vite.config.*"))]:
        try:
            m = re.search(r"(?:localhost|127\.0\.0\.1):(\d{2,5})", (root / name).read_text(errors="replace"))
        except OSError:
            continue
        if m:
            base = f"http://localhost:{m.group(1)}"
            break
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    if not base:
        base = ("http://localhost:5173" if "vite" in deps else "http://localhost:3000" if "next" in deps else None)
    checks = [f"{pm} run {s}" for s in ("lint", "typecheck", "test", "build") if s in scripts]
    return {"start": start, "base_url": base, "deployed_url": None, "local_urls": []}, checks


def fresh_owned(path: str, new: bytes) -> bytes:
    """A project-owned file being created: never copy the template's own settings into the project
    (its request-log artifact url, its start command and address)."""
    name = Path(path).name
    if name == "artifact.json":
        return b'{"url": null}\n'
    if name == "project.json":
        try:
            cfg = json.loads(new or b"{}")
        except ValueError:
            return new
        app, checks = detect_app(ROOT)
        cfg["project_name"] = None
        cfg["app"] = app
        cfg["checks"] = checks
        if isinstance(cfg.get("preview"), dict):
            cfg["preview"]["enabled"] = False
        return (json.dumps(cfg, indent=2, ensure_ascii=False) + "\n").encode()
    return new


GITIGNORE = ["requests_and_response/index.html", "requests_and_response/assets/", "requests_and_response/past.html",
             "requests_and_response/*/derived.js", "requests_and_response/.build.lock",
             "requests_and_response/*/.narrative.*"]


def gitignore_missing() -> list[str]:
    try:
        have = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    except OSError:
        have = set()
    return [line for line in GITIGNORE if line not in have]


def ensure_gitignore() -> None:
    """The request log's build outputs are rebuilt, never committed (one commit per request)."""
    missing = gitignore_missing()
    if missing:
        path = ROOT / ".gitignore"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n# request log build outputs (.claude request-log rebuilds them; never committed)\n" + "\n".join(missing) + "\n"
        path.write_text(text, encoding="utf-8")


def flat_keys(d, prefix="") -> set:
    keys = set()
    if isinstance(d, dict):
        for k, v in d.items():
            if not k.startswith("_comment"):
                keys.add(prefix + k)
                keys |= flat_keys(v, prefix + k + ".")
    return keys


def apply(actions: list[dict]) -> None:
    for a in actions:
        target = ROOT / a["path"]
        kind = a["kind"]
        if kind in ("add", "update", "merge", "config"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(a.get("data", a.get("new")))
            if a.get("mode") == "100755":
                target.chmod(target.stat().st_mode | 0o111)
        elif kind == "conflict":
            side = target.with_name(target.name + ".template")
            side.write_bytes(a["new"])
        elif kind == "delete":
            target.unlink()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo")
    ap.add_argument("--branch")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--project", help="project folder (default: the project this script is in)")
    args = ap.parse_args()
    global ROOT
    if args.project:
        ROOT = Path(args.project).expanduser().resolve()
        if not ROOT.is_dir():
            sys.exit(f"--project {args.project}: no such folder")
    print(f"project: {ROOT}")

    cfg = read_json(ROOT / CLAUDE / "project.json").get("template") or {}
    repo = args.repo or cfg.get("repo") or DEFAULT_REPO
    branch = args.branch or cfg.get("branch") or "main"
    lock = read_json(ROOT / LOCK)

    is_git = run("git", "rev-parse", "--is-inside-work-tree", cwd=ROOT, check=False).returncode == 0
    if args.apply and not args.force:
        if not is_git:
            sys.exit("Not a git repo: the update could not be reviewed or undone. Use --force to apply anyway.")
        dirty = run("git", "status", "--porcelain", "--untracked-files=no", "--", CLAUDE, cwd=ROOT).stdout.decode().strip()
        if dirty:
            sys.exit("Commit or stash the changes in .claude/ first, so the template update is its own diff "
                     "(or use --force):\n" + dirty)

    print(f"template: {repo} ({branch})")
    tpl = Template(repo, branch)
    try:
        if lock.get("commit") == tpl.commit:
            print(f"last update was already at {tpl.commit[:7]}; checking files anyway")
        owned = set(DEFAULT_OWNED) | set(cfg.get("project_owned") or [])
        tpl_cfg = json.loads(tpl.git("show", f"HEAD:{CLAUDE}/project.json") or "{}") if f"{CLAUDE}/project.json" in tpl.files else {}
        owned |= set((tpl_cfg.get("template") or {}).get("project_owned") or [])
        actions = plan(tpl, lock, owned)
        print(f"template commit: {tpl.commit[:7]}" + (f" (last update: {lock['commit'][:7]})" if lock.get("commit") else " (first update: no template-lock.json)"))
        order = ["add", "update", "merge", "config", "conflict", "delete", "orphan", "keep"]
        for kind in order:
            for a in (x for x in actions if x["kind"] == kind):
                print(f"  {kind:<9}{a['path']}" + (f"  - {a['why']}" if a["why"] else ""))
        counts = {k: sum(a["kind"] == k for a in actions) for k in order + ["same"]}
        tpl_paths = set(tpl.files) | set(tpl.history)
        here = [p for p in (ROOT / CLAUDE).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        mine = sorted(str(p.relative_to(ROOT)) for p in here
                      if str(p.relative_to(ROOT)) not in tpl_paths and str(p.relative_to(ROOT)) not in NEVER
                      and not p.name.endswith(".template"))
        print("summary: " + ", ".join(f"{v} {k}" for k, v in counts.items() if v)
              + f"; {len(mine)} project-only file(s) left alone")
        if gitignore_missing():
            print(f"  .gitignore: {len(gitignore_missing())} request-log build output line(s) to add")
        changes = [a for a in actions if a["kind"] not in ("same", "keep", "orphan")]
        if not args.apply:
            print("dry run: nothing written. Run again with --apply to make these changes." if changes else "nothing to update.")
            return
        apply(actions)
        ensure_gitignore()
        files =sorted(p for p in tpl.files if p not in owned)
        (ROOT / LOCK).write_text(json.dumps({
            "repo": repo, "branch": branch, "commit": tpl.commit,
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "files": files}, indent=2) + "\n", encoding="utf-8")
        print(f"applied. Recorded {tpl.commit[:7]} in {LOCK}. Review with: git diff -- .claude")
        print("next: fill in any new project.json keys, commit, then register the project in the projects "
              "directory (.claude/skills/projects-directory/SKILL.md).")
        if counts["conflict"]:
            print("conflicts: compare each file with its .template copy, keep what you need, then delete the .template file.")
    finally:
        tpl.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Log cleanup (the log-cleanup skill; run only when the user asks for it).

    python3 .claude/skills/request-log/log_cleanup.py prepare <summary-slug>
    python3 .claude/skills/request-log/log_cleanup.py archive <summary-slug> --published

prepare  The summary request's folder (request.md, report.html) must exist. Every other request folder
         is covered: all of them must be done and committed. Writes <summary>/summary.json (each covered
         entry's index card data, the period and the totals) and prints a digest to write the summary
         report from: per entry its tasks, errors, open preventions and follow-ups, then the open
         preventions as ready-made errors rows to carry over.
archive  Run after the publish that sent every file (the artifact keeps files a later publish leaves
         out, so the covered reports stay viewable there). Appends the covered cards to
         requests_and_response/past.json with the commit they can be restored from
         (git checkout <commit> -- requests_and_response/<slug>), then deletes the covered folders
         (git rm, plus their untracked build outputs). --published confirms that publish happened.
"""
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_artifact as B  # noqa: E402
import metrics  # noqa: E402

LOG, ROOT = B.LOG, B.ROOT
PAST = LOG / "past.json"
KEEP = ("minutes", "tokens", "review_rounds", "counts", "commit", "started", "ended", "status", "summary", "kind")


def git(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True)


def card_data(r: dict) -> dict:
    d = r["derived"]
    tokens = d.get("tokens") or {}
    return {"slug": r["slug"], "title": r["title"], "started": r["started"], "status": r["status"],
            "verdict": r["verdict"], "follow_ups": r["follow_ups"], "media": [p.name for p in r["media"]],
            "derived": {**{k: d[k] for k in KEEP if k in d}, "tokens": {"total": tokens.get("total", 0)},
                        "open_preventions": d.get("open_preventions", [])}}


def covered(summary: str) -> list[dict]:
    return sorted((B.read_request(f) for f in LOG.iterdir() if (f / "request.md").is_file() and f.name != summary),
                  key=lambda r: r["started"])


def tasks(page: str) -> list[str]:
    out = []
    for row in re.findall(r"<tr>(.*?)</tr>", B.section(page, "tasks"), re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) >= 2:
            out.append(f"{B.plain(cells[0])} {B.plain(cells[1])[:160]}")
    return out


def busy_minutes(entries: list[dict]) -> int:
    """Union of the requests' [started, ended] spans: requests that overlap or share a commit count once."""
    spans = sorted((datetime.fromisoformat(d["started"]), datetime.fromisoformat(d["ended"]))
                   for d in (e["derived"] for e in entries) if d.get("started") and d.get("ended"))
    total, cur = 0.0, None
    for a, b in spans:
        if cur and a <= cur[1]:
            cur = (cur[0], max(cur[1], b))
        else:
            if cur:
                total += (cur[1] - cur[0]).total_seconds()
            cur = (a, b)
    if cur:
        total += (cur[1] - cur[0]).total_seconds()
    return round(total / 60)


def distinct_files(entries: list[dict]) -> int:
    """Files changed by the covered commits, each file once (several requests may share one commit)."""
    shas = {(e["derived"].get("commit") or {}).get("sha") for e in entries} - {None, ""}
    files = set()
    for sha in shas:
        files |= set(filter(None, git("show", "--name-only", "--format=", sha).stdout.splitlines()))
    return len(files)


def totals(entries: list[dict]) -> dict:
    def s(f):
        return sum(f(e["derived"]) or 0 for e in entries)
    return {"requests": len(entries),
            "minutes": busy_minutes(entries),
            "tokens": s(lambda d: d.get("summary", {}).get("tokens") or (d.get("tokens") or {}).get("total")),
            "files": distinct_files(entries),
            "errors": s(lambda d: d.get("summary", {}).get("errors") or (d.get("counts") or {}).get("errors")),
            "review_rounds": s(lambda d: d.get("summary", {}).get("review_rounds") or d.get("review_rounds")),
            "open_preventions": sum(len(e["derived"]["open_preventions"]) for e in entries)}


def prepare(summary: str) -> int:
    folder = LOG / summary
    if not (folder / "request.md").is_file():
        print(f"{folder} has no request.md: start the summary as a normal request first.")
        return 1
    rs = covered(summary)
    if not rs:
        print("Nothing to summarise: no other request folders.")
        return 1
    problems = [f"{r['slug']}: status {r['status']}" for r in rs if r["status"] != "done"]
    problems += [f"{r['slug']}: uncommitted changes" for r in rs
                 if git("status", "--porcelain", "--", f"requests_and_response/{r['slug']}").stdout.strip()]
    if problems:
        print("Cannot summarise yet - finish and commit these first:\n  " + "\n  ".join(problems))
        return 1
    entries = [card_data(r) for r in rs]
    data = {"made": datetime.now().astimezone().isoformat(timespec="minutes"),
            "period": {"from": rs[0]["started"], "to": rs[-1]["started"]},
            "totals": totals(entries), "covers": entries}
    (folder / "summary.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    t = data["totals"]
    print(f"summary.json written: {t['requests']} requests, {data['period']['from']} to {data['period']['to']}, "
          f"{B.dur(t['minutes'])}, {B.tok(t['tokens'])} tokens, {t['files']} files, {t['errors']} errors, "
          f"{t['open_preventions']} open preventions\n")
    for r in rs:
        page = r["report"].read_text(encoding="utf-8") if r["report"] else ""
        sha = r["derived"].get("commit", {}).get("sha", "")
        print(f"## {r['started']}  {r['title']}  ({r['slug']}, {sha or 'no commit'})")
        for line in tasks(page):
            print(f"   task  {line}")
        c = r["derived"].get("counts", {})
        print(f"   errors {c.get('errors', 0)} ({c.get('applied', 0)} applied, {c.get('suggested', 0)} suggested)")
        for f in r["follow_ups"]:
            print(f"   next  {f}")
    rows = [p for e in entries for p in e["derived"]["open_preventions"]]
    print(f"\n## {len(rows)} open preventions to carry over (paste into the summary's errors table, renumber)")
    for p in rows:
        print(f'<tr><td>{p["id"]}</td><td>Carried over from {p["slug"]} {p["id"]}: {B.html.escape(p["what"])}</td>'
              f'<td>See <a href="../{p["slug"]}/report.html#errors">{p["slug"]}</a></td><td>See the original report</td>'
              f'<td>Open</td><td><span class="prev suggested">suggested</span>{B.html.escape(p["prevention"])}</td></tr>')
    return 0


def archive(summary: str, published: bool) -> int:
    folder = LOG / summary
    data_file = folder / "summary.json"
    if not data_file.exists():
        print("No summary.json: run prepare first.")
        return 1
    if not published:
        print("Refusing: publish the artifact with every file from build_artifact.py first (the artifact "
              "keeps them after the folders are deleted), then pass --published.")
        return 2
    data = json.loads(data_file.read_text(encoding="utf-8"))
    slugs = [e["slug"] for e in data["covers"]]
    present = {f.name for f in LOG.iterdir() if (f / "request.md").is_file()} - {summary}
    if present != set(slugs):
        print(f"Folders changed since prepare: run prepare again. now {sorted(present)} vs summary.json {sorted(slugs)}")
        return 1
    restore = git("rev-parse", "--short", "HEAD").stdout.strip()
    past = json.loads(PAST.read_text(encoding="utf-8")) if PAST.exists() else {"cleanups": []}
    past["cleanups"].append({"summary": summary, "title": B.read_request(folder)["title"], "date": data["made"],
                             "restore_commit": restore, "period": data["period"], "entries": data["covers"]})
    PAST.write_text(json.dumps(past, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for s in slugs:
        git("rm", "-r", "-q", "--", f"requests_and_response/{s}")
        shutil.rmtree(LOG / s, ignore_errors=True)  # gitignored leftovers: derived.js, checks run outputs
    print(f"archived {len(slugs)} requests into past.json (restore from {restore}); "
          f"requests_and_response now holds: {sorted(f.name for f in LOG.iterdir() if (f / 'request.md').is_file())}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in ("prepare", "archive"):
        sys.exit(__doc__)
    sys.exit(prepare(a[1]) if a[0] == "prepare" else archive(a[1], "--published" in a))

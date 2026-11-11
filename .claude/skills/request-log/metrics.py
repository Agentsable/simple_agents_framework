#!/usr/bin/env python3
"""Per-request numbers for the report header, the timeline, the diff and the index cards.

    python3 metrics.py <slug>      print one request's metrics as JSON

build_artifact.py calls derive() for every request and writes requests_and_response/<slug>/derived.js
(window.REPORT_DERIVED = {...}); ../assets/report.js draws the KPI strip, the timeline and the diff from
it. derived.js is a build output (gitignored), so rebuilding never leaves the work tree dirty.

Sources, all local:
  report.html            sections: tasks, errors (applied / suggested), follow-ups, verdict
  request.md             Started
  timeline.jsonl         events appended by hooks and log_step.py: plan_ready, step, review_start, review_end
  git                    the request's commit: the request-commit meta of older reports, otherwise the
                         commit that added <slug>/request.md (one commit per request); its time, files, diff
  Claude Code transcripts ~/.claude/projects/<project>/**/*.jsonl: tokens of every assistant message
                         (subagents included) inside the request's time window, counted once per message id.
                         Cost only when .claude/project.json sets metrics.pricing (USD per million tokens).
"""
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
LOG = ROOT / "requests_and_response"
sys.path.insert(0, str(HERE))
from placeholders import has_placeholder  # noqa: E402

DIFF_LIMIT = 300_000  # characters of diff text kept for the diff view


def git(*args: str, timeout: int = 10) -> str:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def config() -> dict:
    try:
        return json.loads((ROOT / ".claude" / "project.json").read_text())
    except (OSError, ValueError):
        return {}


def section(page: str, sid: str) -> str:
    m = re.search(rf'<section id="{sid}"[^>]*>(.*?)</section>', page, re.S)
    return m.group(1) if m else ""


def plain(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def local_dt(text: str) -> datetime | None:
    """'YYYY-MM-DD HH:MM' in local time -> aware datetime."""
    try:
        return datetime.strptime(text.strip()[:16], "%Y-%m-%d %H:%M").astimezone()
    except ValueError:
        return None


def iso_dt(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------- report contents ----------

def rows(fragment: str) -> list[str]:
    return [r for r in re.findall(r"<tr>(.*?)</tr>", fragment, re.S) if "<td" in r]


def report_counts(page: str) -> dict:
    tasks = rows(section(page, "tasks"))
    errs_html = section(page, "errors")
    errs = [] if has_placeholder(errs_html) else rows(errs_html)
    fu = re.findall(r"<li>(.*?)</li>", section(page, "follow-ups"), re.S)
    sizes = [s for li in fu for s in re.findall(r'class="size">\s*([SML])\s*<', li)]
    review = re.search(r'<section id="review" data-verdict="(PASS|FAIL|PENDING)?"', page)
    return {
        "tasks": 0 if has_placeholder(section(page, "tasks")) else len(tasks),
        "errors": len(errs),
        "applied": sum('prev applied' in r for r in errs),
        "suggested": sum('prev suggested' in r for r in errs),
        "review_fails_logged": sum(bool(re.search(r"(?i)evidence review fail", plain(r))) for r in errs),
        "follow_ups": 0 if has_placeholder(section(page, "follow-ups")) else len(fu),
        "sizes": {k: sizes.count(k) for k in "SML" if sizes.count(k)},
        "verdict": (review.group(1) or "") if review else "",
    }


def open_preventions(slug: str, page: str) -> list[dict]:
    """Rows of the errors table whose prevention is still tagged suggested."""
    out = []
    body = section(page, "errors")
    if has_placeholder(body):
        return out
    for r in rows(body):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        if len(cells) < 5 or "prev suggested" not in cells[-1]:
            continue
        prevention = re.sub(r'<span class="prev[^"]*">[^<]*</span>', "", cells[-1])
        out.append({"slug": slug, "id": plain(cells[0]), "what": plain(cells[1])[:240],
                    "prevention": plain(prevention)})
    return out


# ---------- git ----------

def request_commit(folder: Path, page: str) -> str:
    m = re.search(r'<meta name="request-commit" content="([0-9a-f]{7,40})"', page)
    if m:
        return m.group(1)[:7]
    rel = f"{folder.relative_to(ROOT).as_posix()}/request.md"
    return git("log", "--diff-filter=A", "--format=%h", "-1", "--", rel).strip()


def commit_info(sha: str, slug: str) -> dict:
    if not sha:
        return {}
    when = git("show", "-s", "--format=%cI", sha).strip()
    status = git("show", "--format=", "--name-status", "--no-renames", sha)
    files = [line.split("\t", 1) for line in status.splitlines() if "\t" in line]
    added = sum(s.startswith("A") for s, _ in files)
    deleted = sum(s.startswith("D") for s, _ in files)
    # the diff view shows code changes, not the request log itself (reports and evidence images)
    diff = git("show", "--format=", "--no-color", "--no-renames", sha, "--", ".", ":(exclude)requests_and_response")
    truncated = len(diff) > DIFF_LIMIT
    return {"sha": sha, "time": when, "files": len(files), "added": added, "deleted": deleted,
            "modified": len(files) - added - deleted, "diff": diff[:DIFF_LIMIT], "diff_truncated": truncated,
            "diff_label": f"commit {sha}"}


def working_info() -> dict:
    """Not committed yet: the uncommitted changes outside the request log."""
    status = git("status", "--porcelain", "--untracked-files=all")
    files = [l[3:] for l in status.splitlines() if l[3:] and not l[3:].startswith("requests_and_response/")]
    diff = git("diff", "HEAD", "--no-color", "--", ".", ":(exclude)requests_and_response")
    return {"sha": "", "time": "", "files": len(files), "added": sum(l.startswith("??") or l.startswith("A") for l in status.splitlines()),
            "deleted": 0, "modified": 0, "diff": diff[:DIFF_LIMIT], "diff_truncated": len(diff) > DIFF_LIMIT,
            "diff_label": "uncommitted changes (tracked files)"}


# ---------- tokens ----------

def transcript_dir() -> Path:
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))


def tokens(start: datetime, end: datetime) -> dict:
    """Sum of usage for assistant messages timestamped inside [start, end], each message id once."""
    seen: dict[str, dict] = {}
    base = transcript_dir()
    if not base.exists():
        return {}
    lo, hi = start.timestamp(), end.timestamp()
    for f in base.glob("**/*.jsonl"):
        try:
            if f.stat().st_mtime < lo:
                continue
            with f.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"usage"' not in line or '"assistant"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    msg = d.get("message") or {}
                    usage = msg.get("usage")
                    t = iso_dt(d.get("timestamp", ""))
                    if not usage or not t or not (lo <= t.timestamp() <= hi):
                        continue
                    key = msg.get("id") or f'{d.get("requestId")}:{t.timestamp()}'
                    seen[key] = {"model": msg.get("model", "?"), "sub": "/subagents/" in str(f), **usage}
        except OSError:
            continue
    if not seen:
        return {}
    total = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "messages": len(seen), "subagent_messages": 0, "models": {}}
    for u in seen.values():
        part = {"input": u.get("input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0,
                "cache_write": u.get("cache_creation_input_tokens", 0) or 0, "cache_read": u.get("cache_read_input_tokens", 0) or 0}
        for k, v in part.items():
            total[k] += v
        m = total["models"].setdefault(u["model"], {k: 0 for k in part})
        for k, v in part.items():
            m[k] += v
        total["subagent_messages"] += bool(u["sub"])
    total["total"] = total["input"] + total["output"] + total["cache_write"] + total["cache_read"]
    pricing = (config().get("metrics") or {}).get("pricing") or {}
    if pricing:
        cost, priced = 0.0, True
        for model, m in total["models"].items():
            p = pricing.get(model)
            if not p:
                priced = False
                continue
            cost += sum(m[k] * float(p.get(k, 0)) for k in m) / 1_000_000
        total["cost_usd"] = round(cost, 2) if priced else None
    return total


# ---------- timeline ----------

def events(folder: Path) -> list[dict]:
    out = []
    path = folder / "timeline.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if iso_dt(e.get("t", "")):
                out.append(e)
    return sorted(out, key=lambda e: e["t"])


def timeline(start: datetime, end: datetime | None, evs: list[dict], done: bool) -> list[dict]:
    """Bars [label, kind, start, end] in time order: plan, each logged step, review rounds, ship."""
    bars = []
    t = lambda e: iso_dt(e["t"])
    plan_ready = next((t(e) for e in evs if e.get("kind") == "plan_ready"), None)
    first_step = next((t(e) for e in evs if e.get("kind") == "step"), None)
    plan_end = plan_ready or first_step
    if plan_end:
        bars.append({"label": "Plan", "kind": "plan", "start": start, "end": plan_end})
    marks = [e for e in evs if e.get("kind") in ("step", "review_start", "review_end")]
    cursor_label, cursor = None, plan_end
    review_n, review_open = 0, None
    for e in marks:
        when = t(e)
        if e["kind"] == "step":
            if cursor_label and cursor:
                bars.append({"label": cursor_label, "kind": "step", "start": cursor, "end": when})
            cursor_label, cursor = e.get("label", "step"), when
        elif e["kind"] == "review_start":
            if cursor_label and cursor:
                bars.append({"label": cursor_label, "kind": "step", "start": cursor, "end": when})
                cursor_label = None
            review_open = when
        elif e["kind"] == "review_end" and review_open:
            review_n += 1
            v = e.get("verdict") or "?"
            bars.append({"label": f"Review {review_n} · {v}", "kind": "fail" if v == "FAIL" else "review", "start": review_open, "end": when})
            review_open, cursor_label, cursor = None, ("Fix review findings" if v == "FAIL" else None), when
    last = max([b["end"] for b in bars], default=plan_end or start)
    if cursor_label and cursor and (end or not done):
        bars.append({"label": cursor_label, "kind": "step", "start": cursor, "end": end or datetime.now().astimezone()})
        last = bars[-1]["end"]
    if end and end > last:
        bars.append({"label": "Ship" if bars else "Whole request", "kind": "ship", "start": last, "end": end})
    return [{**b, "start": b["start"].isoformat(), "end": b["end"].isoformat(),
             "minutes": round((b["end"] - b["start"]).total_seconds() / 60, 1)} for b in bars if b["end"] >= b["start"]]


# ---------- all together ----------

def derive(folder: Path) -> dict:
    page = (folder / "report.html").read_text(encoding="utf-8") if (folder / "report.html").exists() else ""
    md = (folder / "request.md").read_text(encoding="utf-8")
    m = re.search(r"^- Started:\s*(.+)$", md, re.M)
    start = local_dt(m.group(1)) if m else None
    status = re.search(r'<meta name="request-status" content="([a-z-]+)"', page)
    status = status.group(1) if status else "logged"
    done = status == "done"
    sha = request_commit(folder, page)
    info = commit_info(sha, folder.name) if sha else (working_info() if not done and page else {})
    end = iso_dt(info["time"]) if info.get("time") else (None if done else datetime.now().astimezone())
    evs = events(folder)
    if done and not end and evs:
        end = iso_dt(evs[-1]["t"])
    counts = report_counts(page) if page else {}
    rounds = sum(e.get("kind") == "review_end" for e in evs) or (
        counts.get("review_fails_logged", 0) + (1 if counts.get("verdict") in ("PASS", "FAIL") else 0))
    out = {
        "slug": folder.name, "status": status, "started": start.isoformat() if start else "",
        "ended": end.isoformat() if end else "", "in_progress": not done,
        "minutes": round((end - start).total_seconds() / 60) if start and end else None,
        "review_rounds": rounds, "counts": counts, "commit": {k: v for k, v in info.items() if k != "diff"},
        "diff": info.get("diff", ""), "branch": ((config().get("git") or {}).get("main_branch") or "main"),
        "tokens": tokens(start, end) if start and end else {},
        "timeline": timeline(start, end, evs, done) if start else [],
        "timeline_events": len(evs),
        "open_preventions": open_preventions(folder.name, page) if page else [],
    }
    kind = re.search(r'<meta name="request-kind" content="([a-z-]+)"', page)
    if kind and kind.group(1) == "summary" and (folder / "summary.json").exists():
        # a log-cleanup summary: its cards and KPIs show the totals of the requests it covers
        s = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        out["kind"] = "summary"
        # its errors rows repeat covered errors, so review-FAIL rows there are not its own rounds
        out["review_rounds"] = sum(e.get("kind") == "review_end" for e in evs) or (1 if counts.get("verdict") in ("PASS", "FAIL") else 0)
        out["summary"] = {**s.get("totals", {}), "period": s.get("period", {}),
                          "covers": [{"slug": e["slug"], "title": e["title"], "started": e["started"]} for e in s.get("covers", [])]}
    return out


def write_derived(folder: Path, data: dict) -> Path:
    path = folder / "derived.js"
    path.write_text("window.REPORT_DERIVED = " + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + ";\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    d = derive(LOG / sys.argv[1])
    d["diff"] = f"<{len(d['diff'])} characters>"
    json.dump(d, sys.stdout, indent=2, default=str)
    print()

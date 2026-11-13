#!/usr/bin/env python3
"""Build the shared request-log page, each request's derived data, and the Artifact publish arguments.

Every request lives in its own folder:

    requests_and_response/<slug>/request.md     the request, verbatim, with its "- Started:" time
    requests_and_response/<slug>/report.html    the report, written by Claude (plain sections)
    requests_and_response/<slug>/timeline.jsonl timeline marks from hooks and log_step.py
    requests_and_response/<slug>/*.gif|jpg|png  the evidence shown in the report (names starting
                                                with _ are temporary and never published)
    requests_and_response/<slug>/before|after/  raw UI captures (local only, not published)

Build outputs (gitignored, rebuilt any time, so one commit per request leaves the tree clean):

    requests_and_response/index.html            every request, newest first: status, review, metrics,
                                                evidence, follow-ups, and the Open preventions panel
    requests_and_response/<slug>/derived.js     metrics.py output for that report: KPIs, timeline, diff
    requests_and_response/assets/report.js      the report renderer (report.js + diff2html stylesheet)
    requests_and_response/past.html             Past tasks: every request archived by a log cleanup, from
                                                past.json (committed); their reports stay in the artifact

Prints the Artifact publish arguments as JSON: file_path (the index), files (every report, its
derived.js and media, and the shared assets, at the same relative paths as locally) and url (from
artifact.json). Usage: python3 .claude/skills/request-log/build_artifact.py
The async refresh hooks run it after report edits, commits and reviews; run it yourself before publishing.
"""
import fcntl
import html
import json
import re
import subprocess
import sys
from pathlib import Path

from placeholders import has_placeholder
import metrics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
LOG = ROOT / "requests_and_response"
ASSETS = LOG / "assets"
MEDIA_EXT = {".gif", ".png", ".jpg", ".jpeg", ".webp"}
STATUS = {"planning": "Planning", "in-progress": "In progress", "done": "Done", "logged": "Logged"}
D2H_CSS = HERE / "vendor" / "diff2html-3.4.48.min.css"


def git(*args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def repo_name_from_url(url: str) -> str:
    """Last path part of a git remote URL, without .git: works for https, ssh and scp-style URLs."""
    m = re.search(r"([^/:]+?)(?:\.git)?/*$", url.strip())
    return m.group(1) if m else ""


def project_config() -> dict:
    try:
        return json.loads((HERE.parent.parent / "project.json").read_text())
    except (OSError, ValueError):
        return {}


def site_links() -> str:
    """The links at the top of the log pages: the project's local site (app.base_url) and its
    deployed site (app.deployed_url) from .claude/project.json. An address that is empty or not
    http(s) is shown as "not set" with the setting's name instead of a link."""
    app = project_config().get("app") or {}
    out = []
    for label, key in (("Local site", "base_url"), ("Deployed site", "deployed_url")):
        value = app.get(key)
        urls = [str(u or "").strip() for u in (value if isinstance(value, list) else [value])]  # deployed_url may be a list
        urls = [u for u in urls if re.match(r"https?://[^\s/]+", u)]
        for url in urls:
            shown = re.sub(r"^https?://", "", url).rstrip("/")
            out.append(f'<a class="site" href="{html.escape(url)}" target="_blank" rel="noopener">{label} <code>{html.escape(shown)}</code></a>')
        if not urls:
            out.append(f'<span class="site unset" title="Set app.{key} in .claude/project.json">{label}: not set <code>app.{key}</code></span>')
    return "".join(out)



def repo_web_url(url: str) -> str:
    """The web page of a git remote URL: https and ssh:// URLs and scp-style git@host:org/name.git
    all become https://host/org/name; user names and passwords are dropped. "" if it is not one."""
    url = url.strip()
    m = (re.match(r"^(?:https?|ssh|git)://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/*$", url)
         or re.match(r"^[^@/:\s]+@([^:/\s]+):/?(.+?)(?:\.git)?/*$", url))
    return f"https://{m.group(1)}/{m.group(2)}" if m else ""


def repo_link() -> str:
    """The git repo line of the log pages, under the site links: a link to the web page of the
    project's remote (git.remote in .claude/project.json, default origin), or "not set"."""
    remote = (project_config().get("git") or {}).get("remote", "origin")
    url = repo_web_url(git("remote", "get-url", remote))
    if not url:
        return (f'<span class="site unset" title="Add a git remote named {html.escape(remote)}">'
                f'Git repo: not set <code>git remote {html.escape(remote)}</code></span>')
    shown = re.sub(r"^https://", "", url)
    return f'<a class="site" href="{html.escape(url)}" target="_blank" rel="noopener"><span class="label">Git repo</span> <code>{html.escape(shown)}</code></a>'



def folder_item() -> str:
    """The project's folder on the machine that builds the log (its git top level, else the folder
    that holds .claude/), as selectable text next to the Git repo link. Not a link: browsers do not
    open file:// links from web pages."""
    folder = git("rev-parse", "--show-toplevel") or str(ROOT)
    return (f'<span class="site folder" title="The project folder on the machine that built this page">'
            f'<span class="label">Local folder</span> <code>{html.escape(folder)}</code></span>')


def project_name() -> str:
    """The name shown on the request log. project_name in .claude/project.json wins when set;
    otherwise it follows the git repo: the remote's repo name (git.remote, default origin), then
    the git top-level folder name, then this folder's name."""
    cfg = project_config()
    if str(cfg.get("project_name") or "").strip():
        return cfg["project_name"].strip()
    remote = (cfg.get("git") or {}).get("remote", "origin")
    name = repo_name_from_url(git("remote", "get-url", remote))
    if not name:
        top = git("rev-parse", "--show-toplevel")
        name = Path(top).name if top else ""
    return name or ROOT.name


def section(report_html: str, sid: str) -> str:
    m = re.search(rf'<section id="{sid}"[^>]*>(.*?)</section>', report_html, re.S)
    return m.group(1) if m else ""


def plain(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def follow_ups(report_html: str) -> list[str]:
    """Headline of each item in the report's "Suggested follow-ups" section."""
    items = []
    for li in re.findall(r"<li>(.*?)</li>", section(report_html, "follow-ups"), re.S):
        head = re.search(r"<b>(.*?)</b>", li, re.S)
        text = plain(head.group(1) if head else li)
        if text and not has_placeholder(text):
            items.append(text)
    return items


def verdict(report_html: str) -> str:
    m = re.search(r'<section id="review" data-verdict="(PASS|FAIL|PENDING)"', report_html)
    return m.group(1) if m else ""


def read_request(folder: Path) -> dict:
    text = (folder / "request.md").read_text(encoding="utf-8")
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), folder.name)
    started = re.search(r"^- Started:\s*(.+)$", text, re.M)
    report = folder / "report.html"
    r = {"slug": folder.name, "title": title, "started": started.group(1).strip() if started else "",
         "status": "logged", "report": None, "follow_ups": [], "verdict": "", "derived": {},
         "media": sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXT
                         and not p.name.startswith("_")),  # _name = temporary capture, never published
                         key=lambda p: (p.suffix.lower() != ".gif", p.name))}
    if report.exists():
        page = report.read_text(encoding="utf-8")
        meta = re.search(r'<meta name="request-status" content="([a-z-]+)"', page)
        r.update(report=report, status=meta.group(1) if meta and meta.group(1) in STATUS else "done",
                 follow_ups=follow_ups(page), verdict=verdict(page), derived=metrics.derive(folder))
    return r


def tok(n) -> str:
    if not n:
        return "—"
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{round(n / 1e3)}k" if n >= 1e3 else str(n)


def dur(m) -> str:
    if m is None:
        return "—"
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"


def card(r: dict) -> str:
    """One request's card. r is read_request() output, or a past.json entry (media as file names)."""
    e = html.escape
    s = e(r["slug"])
    d = r["derived"]
    c, k = d.get("counts", {}), d.get("commit", {})
    summ = d.get("summary") if d.get("kind") == "summary" else None
    link = (f'<a class="open" href="{s}/report.html">Open report →</a>'
            if r["report"] else '<span class="open muted">Report not written yet</span>')
    tags = ""
    if r["verdict"]:
        tags += f'<span class="pill v-{r["verdict"].lower()}">Review {r["verdict"]}</span>'
    if c.get("errors"):
        n = c["errors"]
        tags += f'<a class="pill errs" href="{s}/report.html#errors">{n} error{"s" if n != 1 else ""}</a>'
    if k.get("sha"):
        tags += f'<code class="sha">{e(k["sha"])}</code>'
    if summ:
        tags = '<span class="pill kind-summary">Log summary</span>' + tags
    metric_html = ""
    if summ:
        p = summ.get("period", {})
        cells = [("Requests covered", str(summ.get("requests", 0))),
                 ("Period", f'{p.get("from", "")[:10]} – {p.get("to", "")[:10]}'),
                 ("Time", dur(summ.get("minutes"))), ("Tokens", tok(summ.get("tokens"))),
                 ("Files", str(summ.get("files", 0))), ("Errors", str(summ.get("errors", 0)))]
        metric_html = '<div class="metrics">' + "".join(
            f'<div class="m"><div class="k">{a}</div><div class="v">{e(v)}</div></div>' for a, v in cells) + "</div>"
        metric_html += ('<div class="results"><div class="results-label">Covers (full reports under Past tasks)</div><ul class="covers">'
                        + "".join(f'<li><a href="past.html#{e(x["slug"])}">{e(x["title"])}</a></li>' for x in summ.get("covers", []))
                        + "</ul></div>")
    elif r["report"]:
        cells = [("Duration", dur(d.get("minutes")) + (" so far" if d.get("in_progress") else "")),
                 ("Tokens", tok((d.get("tokens") or {}).get("total"))),
                 ("Files", str(k.get("files", 0)) if k else "—"),
                 ("Errors", f'{c.get("errors", 0)}' + (f' · {c.get("suggested")} open' if c.get("suggested") else "")),
                 ("Review rounds", str(d.get("review_rounds") or 0))]
        metric_html = '<div class="metrics">' + "".join(
            f'<div class="m"><div class="k">{a}</div><div class="v">{e(v)}</div></div>' for a, v in cells) + "</div>"
    extra = ""
    if r["media"]:
        figs = "".join(
            f'<figure><a href="{s}/{e(p.name)}"><img loading="lazy" src="{s}/{e(p.name)}" '
            f'alt="{e(p.stem.replace("-", " "))}"></a><figcaption>{e(p.stem.replace("-", " "))}</figcaption></figure>'
            for p in map(Path, r["media"]))
        extra += f'<div class="results"><div class="results-label">Evidence</div><div class="figs">{figs}</div></div>'
    if r["follow_ups"]:
        items = "".join(f"<li>{e(t)}</li>" for t in r["follow_ups"])
        extra += f'<div class="results"><div class="results-label">Suggested follow-ups</div><ol class="next">{items}</ol></div>'
    search = e(f'{r["title"]} {r["slug"]}'.lower() + (" summary" if summ else ""))
    return f'''
  <article class="req" id="{s}" data-status="{e(r["status"])}" data-search="{search}">
    <div class="row">
      <div class="what">
        <h3><a href="{s}/report.html">{e(r["title"])}</a></h3>
        <div class="sub"><time>{e(r["started"]) or "—"}</time><code>{s}</code>{tags}</div>
      </div>
      <div class="side"><span class="pill s-{e(r["status"])}">{STATUS[r["status"]]}</span>{link}</div>
    </div>{metric_html}{extra}
  </article>'''


def total(r: dict, key: str) -> int:
    """A request's own number, or for a log summary the total of what it covers plus its own."""
    d = r["derived"]
    own = {"errors": d.get("counts", {}).get("errors", 0), "tokens": (d.get("tokens") or {}).get("total", 0),
           "rounds": d.get("review_rounds") or 0, "minutes": d.get("minutes") or 0}[key]
    if d.get("kind") == "summary":
        covered = (d.get("summary") or {}).get({"rounds": "review_rounds"}.get(key, key)) or 0
        # its own errors table only repeats covered errors (themes, carried-over preventions), whose
        # review-FAIL rows would also be miscounted as its own rounds: count its own review once
        if key == "errors":
            return covered
        if key == "rounds":
            return covered + (1 if d.get("counts", {}).get("verdict") in ("PASS", "FAIL") else 0)
        return own + covered
    return own


def n_(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def kpis(requests: list[dict]) -> str:
    done = sum(r["status"] == "done" for r in requests)
    covered = sum((r["derived"].get("summary") or {}).get("requests", 0) for r in requests if r["derived"].get("kind") == "summary")
    errors = sum(total(r, "errors") for r in requests)
    open_prev = sum(len(r["derived"].get("open_preventions", [])) for r in requests)
    tokens = sum(total(r, "tokens") for r in requests)
    rounds = sum(total(r, "rounds") for r in requests)
    passed = sum(r["verdict"] == "PASS" for r in requests)
    minutes = sum(total(r, "minutes") for r in requests if r["status"] == "done")
    cells = [("Requests", str(len(requests) + covered), f"{done} done · {len(requests) - done} open"
              + (f" · {covered} in past tasks" if covered else "")),
             ("Errors logged", str(errors), f"{open_prev} preventions still open"),
             ("Review rounds", str(rounds), f'{n_(passed, "report")} passed'),
             ("Time", dur(minutes), "done requests, start to commit, summed" + (" (summaries: overlaps once)" if covered else "")),
             ("Tokens", tok(tokens), "Claude Code transcripts, per request window")]
    return "".join(f'<div class="kpi"><div class="k">{a}</div><div class="v">{html.escape(v)}</div><div class="d">{html.escape(d)}</div></div>'
                   for a, v, d in cells)


def preventions_panel(requests: list[dict]) -> str:
    items = [p for r in requests for p in r["derived"].get("open_preventions", [])]
    if not items:
        return ""
    e = html.escape
    lis = "".join(
        f'<li><div class="src"><a href="{e(p["slug"])}/report.html#errors">{e(p["slug"])}</a> · {e(p["id"])}</div>'
        f'<div><div class="fix">{e(p["prevention"])}</div><div class="was">After: {e(p["what"])}</div></div></li>'
        for p in items)
    return (f'<details class="prevs" id="open-preventions"><summary>Open preventions <small>{len(items)} suggested '
            f'and not yet applied, across {n_(len({p["slug"] for p in items}), "request")} · file them as GitHub issues with '
            f'file_issues.py</small></summary><ul class="prev-list">{lis}</ul></details>')


def load_past() -> list[dict]:
    path = LOG / "past.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("cleanups", []) if path.exists() else []
    except ValueError:
        return []


def past_section(cleanups: list[dict]) -> str:
    n = sum(len(c["entries"]) for c in cleanups)
    if not n:
        return ""
    last = cleanups[-1]
    return (f'<section class="past" id="past-tasks"><h2 class="sec">Past tasks <small>{n_(n, "request")} · '
            f'{n_(len(cleanups), "cleanup")}</small></h2><div class="past-card"><div>'
            f'<b>{n} earlier requests, each with its full report</b><p>Summarised by the log cleanup of '
            f'{html.escape(last["date"][:10])} and earlier; removed from the folder, kept here.</p></div>'
            f'<a class="open" href="past.html">Open past tasks →</a></div></section>')


def page_html(name: str, heading: str, intro: str, section_title: str, count: str, kpi_html: str,
              prevs: str, cards: str, past: str, back: str = "") -> str:
    page = (HERE / "index_template.html").read_text(encoding="utf-8")
    return (page.replace("{{PROJECT}}", html.escape(name)).replace("{{HEADING}}", heading).replace("{{INTRO}}", intro)
                .replace("{{SECTION}}", section_title).replace("{{COUNT}}", count).replace("{{KPIS}}", kpi_html)
                .replace("{{PREVENTIONS}}", prevs).replace("{{BACK}}", back).replace("{{PAST}}", past)
                .replace("{{REQUESTS}}", cards).replace("{{SITES}}", site_links())
                .replace("{{REPO}}", repo_link() + folder_item()))


def write_past(name: str, cleanups: list[dict]) -> Path | None:
    if not cleanups:
        return None
    entries = [dict(x, report=True) for c in cleanups for x in c["entries"]]
    groups = "".join(
        f'<h3 class="group-head">Summarised in <a href="{html.escape(c["summary"])}/report.html">{html.escape(c["title"])}</a>'
        f' · {html.escape(c["date"][:10])} · {len(c["entries"])} requests · restore with '
        f'<code>git checkout {html.escape(c["restore_commit"])} -- requests_and_response/&lt;slug&gt;</code></h3>'
        + "".join(card(dict(x, report=True)) for x in sorted(c["entries"], key=lambda x: x["started"], reverse=True))
        for c in reversed(cleanups))
    done = sum(x["status"] == "done" for x in entries)
    out = LOG / "past.html"
    # published as a second page in the artifact, which gets no document skeleton: bring our own
    out.write_text('<!doctype html>\n<html lang="en">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n' + page_html(
        name, "Past tasks",
        "Every request a log cleanup removed from the folder, with its full report as it was. The main page shows only the summary that replaced them.",
        "Archived requests", f'{n_(len(entries), "request")} · {n_(len(cleanups), "cleanup")}', kpis(entries), "", groups, "",
        back='<a class="back" href="index.html">← Request log</a>'), encoding="utf-8")
    return out


def write_assets() -> Path:
    ASSETS.mkdir(exist_ok=True)
    css = D2H_CSS.read_text(encoding="utf-8") if D2H_CSS.exists() else ""
    out = ASSETS / "report.js"
    out.write_text("window.D2H_CSS = " + json.dumps(css) + ";\n" + (HERE / "report.js").read_text(encoding="utf-8"), encoding="utf-8")
    return out


def build() -> dict:
    LOG.mkdir(exist_ok=True)
    with open(LOG / ".build.lock", "w") as lock:  # async hooks may build at the same time
        fcntl.flock(lock, fcntl.LOCK_EX)
        requests = sorted((read_request(d) for d in LOG.iterdir() if (d / "request.md").is_file()),
                          key=lambda r: r["started"], reverse=True)
        files = {"assets/report.js": str(write_assets())}
        for r in requests:
            if r["report"]:
                files[f'{r["slug"]}/report.html'] = str(r["report"])
                files[f'{r["slug"]}/derived.js'] = str(metrics.write_derived(r["report"].parent, r["derived"]))
            for p in r["media"]:
                files[f'{r["slug"]}/{p.name}'] = str(p)

        name = project_name()
        counts = {k: sum(r["status"] == k for r in requests) for k in STATUS}
        open_ = counts["planning"] + counts["in-progress"]
        cleanups = load_past()
        page = page_html(
            name, "Request log",
            "Every request made to Claude Code in this repo, newest first. Each report holds the plan, a timeline, the verification evidence, the errors met with their root cause and prevention, the diff, the evidence review and the suggested follow-ups.",
            "Requests", f'{n_(len(requests), "request")} · {counts["done"]} done · {open_} open', kpis(requests),
            preventions_panel(requests),
            "".join(card(r) for r in requests) or '<p class="empty">No requests yet. The first request that asks for work appears here.</p>',
            past_section(cleanups))
        index = LOG / "index.html"
        index.write_text(page, encoding="utf-8")
        past = write_past(name, cleanups)
        if past:
            files["past.html"] = str(past)

    config = HERE / "artifact.json"
    url = json.loads(config.read_text())["url"] if config.exists() else None
    return {"file_path": str(index), "files": files, "url": url}


if __name__ == "__main__":
    json.dump(build(), sys.stdout, indent=2)
    print()

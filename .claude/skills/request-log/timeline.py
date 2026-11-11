"""Timeline marks for the current request: requests_and_response/<slug>/timeline.jsonl, one JSON event
per line {"t": ISO time, "kind": ..., ...}. Kinds: plan_ready (the plan gate's sections are filled),
step (log_step.py, one per plan step), review_start / review_end (the evidence-reviewer hooks).
metrics.py turns them into the report's timeline. The file is committed with the request; nothing
writes to it after the request's commit."""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
LOG = ROOT / "requests_and_response"
sys.path.insert(0, str(HERE))
from placeholders import has_placeholder  # noqa: E402


def current_folder() -> Path | None:
    best = ("", None)
    for md in LOG.glob("*/request.md"):
        m = re.search(r"^- Started:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
        if m and m.group(1).strip() > best[0]:
            best = (m.group(1).strip(), md.parent)
    return best[1]


def events(folder: Path) -> list[dict]:
    path = folder / "timeline.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def append(folder: Path, kind: str, **fields) -> dict:
    event = {"t": datetime.now().astimezone().isoformat(timespec="seconds"), "kind": kind, **fields}
    with (folder / "timeline.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def plan_filled(report: Path) -> bool:
    """Same rule as plan-before-edit-gate.sh: understood, tasks and plan have real content."""
    if not report.exists():
        return False
    page = report.read_text(encoding="utf-8")
    for sid in ("understood", "tasks", "plan"):
        m = re.search(rf'<section id="{sid}"[^>]*>(.*?)</section>', page, re.S)
        if not m or has_placeholder(m.group(1)) or len(re.sub(r"<[^>]+>|\s", "", m.group(1))) < 40:
            return False
    return True


def status(report: Path) -> str:
    m = re.search(r'<meta name="request-status" content="([a-z-]+)"', report.read_text(encoding="utf-8")) if report.exists() else None
    return m.group(1) if m else ""

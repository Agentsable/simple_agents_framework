"""Shared helpers for the ui-evidence scripts: project config, the current request slug and its media folder."""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOG = ROOT / "requests_and_response"
PROJECT_FILE = ROOT / ".claude" / "project.json"


def project() -> dict:
    """The project's settings (.claude/project.json); empty if the file is missing."""
    try:
        return json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


APP = project().get("app", {})
DEFAULT_BASE = APP.get("base_url", "http://localhost:5173").rstrip("/")
START_CMD = APP.get("start", "./start.sh")


def current_slug() -> str:
    """The request being worked on: the requests_and_response/<slug>/request.md with the latest `- Started:` time."""
    best = ("", None)
    for md in LOG.glob("*/request.md"):
        m = re.search(r"^- Started:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
        if m and m.group(1).strip() > best[0]:
            best = (m.group(1).strip(), md.parent.name)
    if not best[1]:
        sys.exit("No request found: save the request first (request-log step 1).")
    return best[1]


def media_dir(slug: str) -> Path:
    path = LOG / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def require_server(base: str) -> None:
    try:
        urllib.request.urlopen(base, timeout=5)
    except Exception as error:  # noqa: BLE001
        sys.exit(f"The app is not reachable at {base} ({error}). Start it with {START_CMD} first.")


def wait_ready(page, ready=None, timeout_ms: int = 15000) -> None:
    """Wait until the app says it is ready, not until the network is quiet.

    `ready` (from pages.json, per view or top level):
      "css selector"        - wait until that element is visible (e.g. "[data-ready]", "main h1")
      "js:<expression>"     - wait until the expression is truthy (e.g. "js:!document.querySelector('.spinner')")
      None                  - fall back to network idle, capped at 5 s: live apps (streaming, polling,
                              websockets) are never network-idle, so configure `ready` for them.
    """
    if not ready:
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:  # noqa: BLE001 - never idle; the settle check in the caller still applies
            pass
        return
    if ready.startswith("js:"):
        page.wait_for_function(ready[3:], timeout=timeout_ms)
    else:
        page.wait_for_selector(ready, state="visible", timeout=timeout_ms)


class Checks:
    """Named checks a flow records; record_flow.py writes them to <name>-checks.json.

    In a flow:  def run(page, base_url, check): ...
        check("saved name shows in header", header == "Ada", f"header={header!r}")
        check.equal("cart count after Add", page.locator("#count").inner_text(), "1")
        check.changed("total after Add", before_total, page.locator("#total").inner_text())
    Check a value the action must change, not "the page looks different".
    """

    def __init__(self) -> None:
        self.items: list[dict] = []

    def __call__(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append({"name": name, "result": "PASS" if ok else "FAIL", "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
        return bool(ok)

    def equal(self, name: str, actual, expected) -> bool:
        return self(name, actual == expected, f"expected {expected!r}, got {actual!r}")

    def changed(self, name: str, before, after) -> bool:
        return self(name, before != after, f"before {before!r}, after {after!r}")

    @property
    def failed(self) -> list[dict]:
        return [c for c in self.items if c["result"] != "PASS"]

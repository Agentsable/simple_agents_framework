#!/usr/bin/env python3
"""File every open prevention (an errors-table row still tagged suggested) as a GitHub issue.

    python3 .claude/skills/request-log/file_issues.py            dry run: print what would be filed
    python3 .claude/skills/request-log/file_issues.py --create   create the missing issues with gh

Issue title: "[prevention] <slug> <E#>: <prevention, shortened>". An issue whose title starts with
"[prevention] <slug> <E#>:" already exists (open or closed) -> skipped, so running it again is safe.
Creating issues publishes text to GitHub: run --create only when the user asked for it.
"""
import json
import subprocess
import sys

from metrics import LOG, open_preventions


def existing_titles() -> set[str]:
    out = subprocess.run(["gh", "issue", "list", "--state", "all", "--limit", "500", "--search", "[prevention] in:title",
                          "--json", "title"], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        sys.exit(f"gh issue list failed: {out.stderr.strip()}")
    return {i["title"] for i in json.loads(out.stdout or "[]")}


def main() -> None:
    create = "--create" in sys.argv
    items = []
    for folder in sorted(p for p in LOG.iterdir() if (p / "report.html").exists()):
        items += open_preventions(folder.name, (folder / "report.html").read_text(encoding="utf-8"))
    titles = existing_titles()
    filed = skipped = 0
    for p in items:
        key = f'[prevention] {p["slug"]} {p["id"]}:'
        title = f'{key} {p["prevention"][:90]}'.rstrip()
        if any(t.startswith(key) for t in titles):
            skipped += 1
            print(f"exists   {key}")
            continue
        body = (f'Open prevention from the request log.\n\n**Request:** `{p["slug"]}` ({p["id"]}), '
                f'requests_and_response/{p["slug"]}/report.html#errors\n\n**After:** {p["what"]}\n\n'
                f'**Prevention (suggested):** {p["prevention"]}\n\nWhen it is applied, tag the row '
                f'`applied` in the report and close this issue.')
        if create:
            r = subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], capture_output=True, text=True, timeout=60)
            print(("created  " + r.stdout.strip()) if r.returncode == 0 else f"FAILED   {key} {r.stderr.strip()}")
            filed += r.returncode == 0
        else:
            print(f"would    {title}")
    print(f"{len(items)} open preventions · {skipped} already filed · " + (f"{filed} created" if create else "dry run (use --create)"))


if __name__ == "__main__":
    main()

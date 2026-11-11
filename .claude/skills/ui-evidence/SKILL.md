---
name: ui-evidence
description: Verification evidence for this repo's tasks. (1) Any change that can affect the UI - before/after screenshots of every app view, the before shots taken in the browser BEFORE the first UI edit. (2) Any change to an action sequence or to how a button/event reacts - record the flow with Playwright, convert it to a GIF, verify from the GIF (never the video). Ends with the evidence-reviewer agent reviewing the report, then push.
---

# UI evidence

Two kinds of evidence; a task can need both. All files go into the current request's own folder,
`requests_and_response/<slug>/` (the scripts find it from the latest `- Started:` time in
`<slug>/request.md`), next to its `report.html`, which shows them by file name only. They are
published with the report in the shared request-log artifact. The app must be running (`app.start` and `app.base_url` in `.claude/project.json`).

## Decide at planning time (request-log steps 3-4)

| The change... | Evidence | Put in the plan |
| --- | --- | --- |
| can change what any page shows (components, styles, panel YAML/markdown copy, layout, data shown) | **UI before/after** | a first *single* step "capture BEFORE", before any edit |
| changes an action sequence, or what a button / event / message does | **Flow GIF** | a flow script per behaviour, recorded at the end |
| neither (server only, docs, tooling) | none - say so in the report's Verification list | - |

When unsure, take the before shots: they cost about 20 seconds and cannot be taken later.

## 1. UI before/after

1. **Before any edit that can affect the UI**:
   `python3 .claude/skills/ui-evidence/capture_pages.py before`
   It captures every view in `pages.json` to `requests_and_response/<slug>/before/`. The `ui-before-gate.sh` hook
   blocks edits to files matching `ui_paths` in `.claude/project.json` until this exists. If the task truly cannot change the UI, write the reason
   to `requests_and_response/<slug>/before/SKIP` instead.
2. Make the change.
3. **After**: `python3 .claude/skills/ui-evidence/capture_pages.py after`. It captures the same
   views, compares the pixels with before, and for each changed view writes `ui-<view>.jpg`
   (BEFORE | AFTER, side by side) and `ui-changes.json`.
4. In the report's Evidence, show every `ui-<view>.jpg` as a figure with a caption saying what
   changed. List the unchanged views in one line. A view that changed unexpectedly is a bug to
   explain or fix.

New page, panel or tab in the app? Add it to `pages.json` (name, url, buttons to click) in the same
task.

**When is a view ready?** Set `ready` in `pages.json`, at the top level or per view, to a CSS selector
that is visible only once the app has loaded (e.g. `"[data-ready]"`, `"main h1"`) or to
`"js:<expression>"`. Without it the capture waits for network idle for at most 5 s, which a live app
never reaches. A view that never becomes ready makes the capture exit 1 (images are still saved).

## 2. Flow GIF (behaviour changes)

1. Write a flow script (keep it in the scratchpad, or in `requests_and_response/<slug>/flows/` to keep it):
   ```python
   from evidence_common import wait_ready

   def run(page, base_url, check):
       page.goto(base_url, wait_until="load")
       wait_ready(page, "[data-ready]")          # the app's ready signal, never "networkidle"
       before = page.get_by_test_id("header-name").inner_text()
       page.get_by_role("button", name="Open settings", exact=True).click()
       page.get_by_label("Display name").fill("Ada")
       page.get_by_role("button", name="Save", exact=True).click()
       page.get_by_test_id("header-name").filter(has_text="Ada").wait_for()  # wait for the reaction itself
       page.wait_for_timeout(1500)                # keep it on camera
       after = page.get_by_test_id("header-name").inner_text()
       check.changed("header name changes on Save", before, after)
       check.equal("header shows the saved name", after, "Ada")
   ```
   Make every step visible: wait after each action so the reaction shows in the recording.
   **Checks** (`check(name, ok, detail)`, `check.equal`, `check.changed`) are what make the flow
   pass or fail. Each one reads a value the action must change: a count, a field, a row, a URL.
   "The page text changed" is not a check, because a spinner or an error message also changes it.
   **Wait for the reaction or the app's ready signal, not for the network.** Live apps (streaming,
   polling, websockets) never go network-idle, and a timed wait races the app's own updates.
2. `python3 .claude/skills/ui-evidence/record_flow.py <flow.py> --name <flow-name>`
   Playwright records the video, ffmpeg converts it to `<flow-name>.gif`, the video is deleted,
   `<flow-name>-frames.jpg` is cut from the GIF at the moments the screen changed, and the checks
   go to `<flow-name>-checks.json`. The script exits 1 when a check failed, the flow raised an error,
   or the flow made no checks. The GIF is still written so you can see what went wrong.
3. **Verify from the GIF**: Read `<flow-name>-frames.jpg` (an image viewer shows only a GIF's first
   frame). Confirm each action and its reaction appear in order. Never send or review the video.
4. In the report's Evidence, show `<flow-name>.gif` with a caption describing the sequence, plus the
   frames image and the checks (name and result, quoted from the checks file).

## 3. Review, then push

When the report's execution summary and evidence are written:

1. Launch the **evidence-reviewer** agent (`.claude/agents/evidence-reviewer.md`) with the slug. It
   checks the report against the evidence and writes its verdict (PASS / FAIL) into the report's
   Evidence review section.
2. On FAIL, fix what it lists and run it again.
3. On PASS, add one line to the report's Verification list ("Evidence review: PASS"), set the
   status to done, republish the artifact, commit and push (task-done).

The `evidence-gate.sh` Stop hook blocks ending the turn while any of these is missing: an AFTER
capture for a request with BEFORE shots, a changed view's image or a GIF not shown in the report,
a GIF without a `<name>-checks.json` holding at least one check and no FAIL, or a done report
without a PASS review, task summary or follow-ups.

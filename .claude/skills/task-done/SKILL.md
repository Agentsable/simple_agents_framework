---
name: task-done
description: End-of-task workflow for this repo. Run after finishing any code task, before telling the user it is done - run the project checks and verify the local app in Chrome, push to the main branch, verify the hosted preview (when the project has one), fill the task summary in the request's report.html. Also when the user says "task done", "ship it", or "/task-done".
---

# Task-done workflow

Run these in order. If a step fails, stop, fix it (or report it with the
exact error), and do not continue to the next step on a failure.

All project-specific values come from `.claude/project.json`:

| Key | Used for |
| --- | --- |
| `app.start`, `app.base_url` | starting the app and the URL to open in Chrome |
| `checks` | commands that must pass before pushing (lint, build, tests) |
| `git.remote`, `git.main_branch`, `git.never_commit` | where to push, and files never to commit |
| `preview.enabled`, `preview.instructions` | whether and how to verify the hosted build after a push |

## 1. Verify locally
1. Run every command in `checks`; each must pass.
2. Start the app (`app.start`) in the background if it is not already running.
3. In Chrome (new tab), open every page the task touched plus the start page (`app.base_url`).
   Exercise the changed behaviour itself, not just page load. Evidence follows
   `.claude/skills/ui-evidence/SKILL.md`: before/after of every changed view for UI changes, and a
   Playwright-recorded flow GIF (reviewed from the GIF, never the video) for behaviour changes.
4. Reload once, then read the console messages (errors only) - must be clean.

## 1b. Evidence review
Run the `evidence-reviewer` agent on the request slug. Push only after it has written
`data-verdict="PASS"` into the Evidence review section of `requests_and_response/<slug>/report.html`.

## 2. Task summary, then ONE commit and push
1. Stage everything for the request: `git add -A` (never the files in `git.never_commit`; the request
   log's build outputs are gitignored).
2. Fill the report's Task summary from `git diff --cached --name-status` (section 4 below) and make
   sure the report is `done` with its PASS review, then `git add` the report again.
3. One commit (conventional message + attribution trailer), merge into the main branch
   (fast-forward if possible) and push. The commit sha is never written into the report: the
   builder looks it up from git (the commit that added the request's `request.md`) and shows it in
   the header and on the index card. So there is no second commit.
4. `python3 .claude/skills/request-log/build_artifact.py` and publish the artifact.
5. Refresh this project's row in the projects directory: follow
   `.claude/skills/projects-directory/SKILL.md` (run `register_project.py`, write the printed row
   with `ArtifactData`). Each push gets the next version number there.

## 3. Verify the hosted preview (only if `preview.enabled`)
Follow `preview.instructions`: wait until the pushed commit is built and deployed, open the preview
URL in Chrome, and repeat steps 1.3-1.4 there. A failed build stops the flow: fix, push, re-check.
Do not deploy to production unless the user asks.

Example `preview.instructions` for a Base44 app connected to GitHub:
`POST /api/apps/{app_id}/github/sync` (already_up_to_date = webhook already pulled it,
merge_conflict = stop and report), poll get_app_status until ready, then
`GET /api/apps/{app_id}/sandbox/preview-url` and open `https://<preview_url>` (409 = the app does
not build).

## 4. The report's Task summary (filled in step 2, before the commit)
There is no separate summary file: the task summary is a section of
`requests_and_response/<slug>/report.html`. Fill `<section id="task-summary">`:

- **Task** - what was asked, 1-3 lines
- **Changes by file** - one table row for every file in `git diff --cached --name-status`:
  added / modified / deleted, what changed and why
- **Shipped verification** - Local (pages checked, result), Hosted preview (url, pages checked,
  result - or "no preview configured"), Not verified (anything skipped, or "nothing")

The report is part of the single commit, so the request folder in git matches the artifact.
If the hosted preview (step 3) fails after the push, fix it in a new commit and add a row to the
report's errors section in that commit.

Finish by telling the user: commit sha, preview link (if any), the request-log artifact link, and the
suggested follow-ups as a short list they can pick from.

---
name: request-log
description: Per-request log for this repo. Run at the start of every user request that asks for work - create the folder requests_and_response/<slug>/ with request.md and report.html (understanding, interpretations, task/verification table, parallel-optimised plan), publish the shared request-log Claude artifact, keep both updated while working, and finish with the execution summary, Chrome evidence (before/after, flow GIFs) in the same folder, task summary, evidence review and suggested follow-ups - all inside report.html.
---

# Request log workflow

Every user request that asks for work gets **its own folder** in `requests_and_response/`, named by a
short kebab-case slug. Everything about the request lives there and nowhere else:

```
requests_and_response/
├── index.html                  BUILD OUTPUT: every request, newest first, plus Open preventions
├── assets/report.js            BUILD OUTPUT: draws each report's KPIs, timeline and diff
├── past.json                   cards of the requests removed by log cleanups (committed)
├── past.html                   BUILD OUTPUT: Past tasks page, from past.json
└── <slug>/
    ├── request.md              the request, verbatim, with its start time
    ├── report.html             the whole story, written by you as plain sections: understanding,
    │                           plan, evidence, errors and prevention, task summary, review, follow-ups
    ├── timeline.jsonl          timeline marks (hooks + log_step.py); committed with the request
    ├── checks/*.txt            optional: verbatim check output saved with tee (headless narrative input)
    ├── derived.js              BUILD OUTPUT: metrics.py numbers for this report (KPIs, timeline, diff)
    ├── ui-<view>.jpg  <flow>.gif  <flow>-frames.jpg  <flow>-checks.json  *.jpg   evidence
    ├── ui-changes.json
    └── before/  after/         raw UI captures (kept locally, not published)
```

Build outputs are gitignored and rebuilt by `build_artifact.py` (the async hooks run it after report
edits, git commits and reviews). That is what makes **one commit per request** possible: nothing in
git changes after the commit.

There are no other per-request files: the task summary and the evidence review are sections of
`report.html`, not separate markdown files.

All requests share **one request-log artifact** (a Claude artifact). Its front page is
`requests_and_response/index.html`: every request with its start time, status, review verdict,
commit, evidence thumbnails and follow-ups, with status filters and search; each title opens that
request's report, and each report links back to the list. Every publish includes all requests, so
nothing is ever dropped from it.

Skip only pure questions that change nothing. A follow-up that just continues the previous request
adds its text to that request's `request.md` (under `## Follow-up N (verbatim)`) and updates that
request's report and the artifact instead of starting a new folder.

Files used by this workflow (all next to this file):

| File | Purpose |
| --- | --- |
| `report_template.html` | Layout and sections of every `report.html` |
| `index_template.html` | The shared index page (all requests) |
| `build_artifact.py` | Writes the index, every `derived.js` and `assets/report.js`, and prints the publish arguments |
| `metrics.py` | Per-request numbers: duration, tokens (Claude Code transcripts in the request's time window), files, errors applied/suggested, review rounds, timeline bars, the commit and its diff |
| `report.js`, `vendor/diff2html-*.css` | The report renderer (Mermaid gantt, diff2html diff), copied to `assets/report.js` |
| `timeline.py`, `log_step.py` | Timeline marks; run `log_step.py "<step>"` at the start of each plan step |
| `file_issues.py` | Files open preventions as GitHub issues (dry run unless `--create`; only when the user asks) |
| `log_cleanup.py` | The log-cleanup skill's prepare/archive steps (only when the user asks for a cleanup) |
| `artifact.json` | `{"url": "<artifact url>"}` - the one artifact all requests are published to (`null` until the first publish) |

The project name shown on the index is the git repo's name, taken from the `git.remote` URL in
`.claude/project.json` (falling back to the git top-level folder name, then this folder's name). Set
`project_name` there only to override it with a display name.

The index and the Past tasks page start with links to the project's **local site** (`app.base_url`)
and **deployed site** (`app.deployed_url`), both from `.claude/project.json`. An address that is
empty or not http(s) shows as "not set" with the setting's name. Under them, on its own line, is a link to the
project's **git repo**: the web page of the `git.remote` remote (ssh and scp-style URLs become https,
credentials are dropped), or "Git repo: not set" when the project has no remote. Next to it, **Local folder** shows the full path of the
project's folder on the machine that built the page (its git top level), as text you can select and
copy.

## The sequence

### 1. Save the request (first tool call of the request)

Pick a short kebab-case slug not in `ls requests_and_response/`, note the start time
(`date "+%Y-%m-%d %H:%M"`) and write `requests_and_response/<slug>/request.md`:

```markdown
# <Title in a few words>

- Date: <YYYY-MM-DD>
- Started: <YYYY-MM-DD HH:MM>

## Request (verbatim)

<the user's message exactly as typed - typos included, nothing fixed>
```

The hooks and evidence scripts treat the folder whose `request.md` has the latest `- Started:` time
as the current request. If the user points to an existing request folder, that is the request: keep
its slug.

### 2. Write the report (understanding) and publish

Copy `report_template.html` to `requests_and_response/<slug>/report.html`, set
`<meta name="request-status" content="planning">` and the start time, and fill:

- **Original request (verbatim)** - the text from `request.md`, HTML-escaped, in `<pre>`.
- **What I understood was requested** - one bullet per concrete deliverable or constraint.
- **Interpretations** - every ambiguous point: quote the wording, the readings considered, the one
  chosen and why. "None." if nothing was ambiguous - never omit the section.

Leave the later sections as they are until their step. Then publish (see *Publishing the artifact*)
so the request appears in the shared artifact with its start time.

### 3. Tasks and how they will be verified

Decide which verification the task needs (`.claude/skills/ui-evidence/SKILL.md`):
- **UI before/after** if anything a page shows can change. The BEFORE capture is the plan's first
  step, taken before any edit.
- **Flow GIF** if an action sequence, or what a button or event does, changes.
- Name both in the tasks table.

Fill **Tasks and how each is verified**: a table of tasks `T1..Tn`, each with what it depends on and
the concrete check that proves it done (a command and its expected output, a test, a Chrome step, a
screenshot to compare). Split the work so tasks that don't depend on each other can run at the same
time: separate files, separate layers, research vs. implementation, independent verifications.

### 4. Numbered implementation plan

Fill **Implementation plan**: an ordered list where every step is either
`<span class="tag single">single</span>` (one task) or `<span class="tag parallel">parallel</span>`
(tasks run at the same time - name them, e.g. `T2 ‖ T3 ‖ T4`). Put a task in a parallel step whenever
its dependencies are all in earlier steps. Execute parallel steps as parallel work: several
independent tool calls in one message, or subagents for larger independent tasks.

**Plan before edit.** The `plan-before-edit-gate.sh` PreToolUse hook blocks Edit, Write, MultiEdit
and NotebookEdit on any project file outside `requests_and_response/` until the current request's
report has What I understood, Tasks and Implementation plan filled in (no template fields left).
Steps 1-4 therefore always come before the first code edit. The hook cannot see edits made through
Bash (sed, heredocs), so don't use those to get around it.

### 5. Update the report and the artifact

After steps 3-4, set the status to `in-progress`, save, and publish again. Do the same whenever
the plan changes materially while working (a step added, dropped or reordered).

At the start of each plan step run `python3 .claude/skills/request-log/log_step.py "<step label>"`.
The report's Timeline draws a bar per step, plus the plan time (the `plan_ready` mark, set by the
`refresh-log.sh` hook when the plan is first filled), every review round (from the reviewer hooks;
FAIL rounds in red), and shipping (to the commit). You never rebuild by hand while working: the
async hooks do it. Save verbose check output with `tee requests_and_response/<slug>/checks/<name>.txt`
and quote it from there, so it is read once.

### 6. Execution summary, evidence, follow-ups, review (when the work is done)

Fill **Execution summary**: what each step did (files changed), anything skipped or left open, and
the result of every task's check under **Verification**. Under **Evidence** include images or GIFs
from the Chrome verification. All of them are files in the request folder, referenced by file name
only (`src="ui-home.jpg"`), so the same report works locally and in the artifact:

- **UI changes:** `capture_pages.py after`, then every `ui-<view>.jpg` (before | after) as a figure.
- **Behaviour changes:** `record_flow.py` → `<name>.gif` + `<name>-frames.jpg`; review the frames
  image, never the video.
- Other screenshots: save them into the request folder (JPG ~1200px wide).

Fill **Errors and prevention**: one row for every error during the request - a failed or rejected
command or tool call, a hook that blocked, an evidence-review FAIL, a wrong assumption caught later,
anything that had to be redone. Keep a running list while working so nothing is lost by the end.
Each row gives what went wrong (quote the error text), the immediate cause, the **root cause as a
short why-chain** (ask "why?" until the answer is something the template, a hook, a script or a check
can change: "why? ... → why? ... → root: ..."; stopping at "I typed it wrong" is not a root), how it
was resolved, and a concrete prevention that removes that root: a change to a hook, skill, script,
template or check, or (weaker) a working habit. A defect found and fixed while testing is an error too. Tag it `applied` (say where) when you made that change in this request, or
`suggested` when you did not. Before writing a prevention, read the earlier reports' sections: an
error that already happened in an earlier request should get an applied fix, or become a follow-up.
If nothing went wrong, write `<p>No errors.</p>`. When quoting double braces in any report text,
write them as `&#123;&#123;` so they never look like a template field.

A section counts as unfilled while it contains a template field - a closed pair of double braces
around a short label (`placeholders.py` next to this file holds the rule; the hooks, the builder and
the reviewer all use it). The index shows the error count on each card, and every prevention still
tagged `suggested` in any report appears in the index's **Open preventions** panel until a later
request applies it: then re-tag that old row `applied` and say where.

Fill **Suggested follow-ups**: 2-5 next steps, most valuable first, that carry the user's underlying
goal further (read the request and its interpretations for what they are ultimately after). Each item
is phrased as a request the user could send as-is, tagged S / M / L for size, with one line on why:
a gap left open in this request, a risk or weakness noticed while working, a check that could not be
run, or the natural next capability. No generic advice ("add more tests") unless tied to something
specific seen in this work. The index shows them on the request's card.

Then run the **evidence-reviewer** agent on the slug. It always runs in the background
(`background: true`), so keep working while it reviews. Just before launching it, set the report's
review section to `<section id="review" data-verdict="PENDING">` (and again before every re-run):
the `task-done-gate.sh` Stop hook stays quiet while a PENDING review is less than 45 minutes old.
The `reviewer-bookkeeping.sh` hooks record each round on the timeline, rebuild when it ends, and
clear a PENDING mark the reviewer left behind. The reviewer writes its verdict into the **Evidence
review** section (`data-verdict="PASS"` or `"FAIL"`). On FAIL, fix what it lists and run it again.
On PASS, set the status to `done` and finish with the task-done workflow: fill the **Task summary**
from the staged diff, then make **one commit** and push. For a request that changed no code, write
"No code changes - nothing pushed." in the Task summary.

Publish the artifact once more at the very end (build_artifact.py, then publish), so it shows the
final report with its commit.

**Headless narrative (opt-in):** with `"headless_narrative": {"enabled": true}` in
`.claude/project.json`, the async `headless-narrative.sh` Stop hook drafts the Execution summary and
Errors sections from `<slug>/checks/*.txt` in a separate `claude -p` run (Haiku by default) while you
move on. Leave those two sections alone until it finishes (`<slug>/.narrative.lock` is gone), then
review and correct them: it cannot tell a deliberate negative test from a real failure.

The `evidence-gate.sh` Stop hook will not let a `done` report end the turn while its Errors and
prevention section, Task summary, PASS review or follow-ups are missing, or while evidence in the folder is not shown in the report.

## Publishing the artifact

```bash
python3 .claude/skills/request-log/build_artifact.py
```

writes `requests_and_response/index.html`, every `derived.js` and `assets/report.js`, and prints
`{"file_path", "files", "url"}`: the index page, every request's `report.html`, `derived.js` and
evidence (published at `<slug>/<file>`, the same paths as locally), `assets/report.js`, and the
artifact URL. On an update, send only the files that changed (always the current report and its
`derived.js`); the artifact keeps the rest. Call the Artifact tool's publish with that `file_path`, `files` and `url`.

- **First publish in this project** (`url` is null): pass `icon: "list"` and a one-line
  `description`, then save the returned URL to `.claude/skills/request-log/artifact.json` as
  `{"url": "..."}` and commit it. Every later publish, for every request, goes to that same URL.
- **New session:** `read` the artifact once before publishing to it (the Artifact tool refuses a
  publish to an artifact the session has not read).
- Never publish a single report as its own artifact: the shared artifact is how the user sees all
  requests in one place.

Give the user the artifact link and the suggested follow-ups when the request is done.

## Log cleanup (only on request)

When the user asks to clean up the log, follow `.claude/skills/log-cleanup/SKILL.md`. It writes one
summary request (`<meta name="request-kind" content="summary">`) covering every request since the
last cleanup. The covered folders are removed and their cards go into `requests_and_response/past.json`
(committed). The artifact keeps their full reports, listed on `past.html` (Past tasks), while the main
page shows only the summary and newer requests. Because of that, always publish to the URL in
`artifact.json`: a new artifact would not have the past reports.

---
name: log-cleanup
description: Log cleanup for this repo's request log - only when the user asks for it ("/log-cleanup", "clean up the log"). Writes one summary request that describes everything done since the last cleanup in a few process tasks, keeps every covered report in full under Past tasks in the request-log artifact, and removes the covered folders from requests_and_response/ so only the summary remains.
disable-model-invocation: true
---

# Log cleanup

Run this only when the user asks. It deletes request folders (they stay in git history and in the
artifact), so never start it on your own.

**Result:**
- `requests_and_response/` holds one summary request, plus any request made after it.
- The artifact's main page shows only those requests. A **Past tasks** section links to `past.html`.
- `past.html` lists every removed request as its full index card, grouped by cleanup. Each card
  opens the original report, evidence and diff exactly as they were published.

## Sequence

1. **Start the summary as a normal request** (request-log steps 1-4).
   - Use the slug `log-summary-<YYYY-MM-DD>` and the title "Log summary <first date> – <last date>".
   - In the report's head, add `<meta name="request-kind" content="summary">` under the
     `request-status` meta. The header then shows the covered totals, and the card is tagged Log summary.
   - The request text is the user's cleanup request.
2. **Prepare:** `python3 .claude/skills/request-log/log_cleanup.py prepare <slug>`.
   - It covers every other folder, including a previous summary. It refuses while any of them is not
     `done` or has uncommitted changes, so finish or commit those first.
   - It writes `<slug>/summary.json` (each covered card, the period, the totals). It prints a digest:
     per request its tasks, errors and follow-ups, then the open preventions as errors rows.
3. **Write the summary report** from the digest. It must read like a normal report, telling the
   story of the whole period:
   - What I understood: what the period set out to do and what it achieved, in a few lines.
   - Tasks: 3-6 **process tasks**, each grouping the requests that built one capability (for example
     "Request log and per-request reports", "Evidence and review gates", "Metrics and redesign").
     The Depends on column names the slugs; Verified by names the covered reviews and commits.
   - Implementation plan: the phases in the order they happened.
   - Execution summary: one paragraph per process task: what was built, what changed along the way, why.
   - Errors and prevention:
     - recurring error themes, with their root cause
     - every open prevention from the digest's rows, still tagged `suggested`, so the backlog
       survives the cleanup
   - Suggested follow-ups: the covered follow-ups that are still open, merged and deduplicated.
   - Leave the timeline, KPIs and diff to the build: they show the covered totals.
4. **Review:** set the review to PENDING and run the evidence-reviewer. Fix it until PASS, then set
   the status `done`.
5. **Publish everything:** run `build_artifact.py` and publish with **every** file it lists, not only
   the changed ones. This is the last time the covered reports are sent. The artifact keeps them
   after the folders are gone.
6. **Archive:** `python3 .claude/skills/request-log/log_cleanup.py archive <slug> --published`.
   - It appends the covered cards to `requests_and_response/past.json` (committed), with the commit
     they can be restored from.
   - It then removes the covered folders (git rm).
7. **Ship:** `build_artifact.py` (it now writes `past.html`), `git add -A`, fill the Task summary from
   `git diff --cached --name-status`, one commit, push, then build and publish the index,
   `past.html` and the summary's files to the same artifact URL.

## Rules

- **Always publish to the artifact URL in `artifact.json`.** After a cleanup, the covered reports
  exist only in that artifact and in git history. Never start a new artifact. To rebuild past pages
  elsewhere, run
  `git checkout <restore_commit> -- requests_and_response/<slug>` for the slugs in `past.json`.
- `past.json` is append-only: one entry per cleanup. A request listed there never comes back to the
  main page.
- A later cleanup covers the previous summary too. That summary then moves to Past tasks, and the
  new summary lists it among the requests it covers.

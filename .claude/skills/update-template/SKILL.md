---
name: update-template
description: Update this project's .claude/ folder from the template repo (https://github.com/spiceroutes/claude_template_request_tasks_and_evidance_html.git) without losing local work. Use when the user says "update the template", "update against the template", "update from the template", "pull the latest template", "sync .claude with the template" or "/update-template".
---

# Update the template

This project's `.claude/` folder (hooks, skills, agents, settings) came from a template repo. This
action brings in the template's newer version while keeping everything the project changed or added.

- **Template repo:** `template.repo` in `.claude/project.json`, by default
  `https://github.com/spiceroutes/claude_template_request_tasks_and_evidance_html.git`
  (branch `template.branch`, default `main`).
- **What is updated:** only files under `.claude/` that come from the template. The template's other
  folders (its own `requests_and_response/`, designs) are never copied.
- **Script:** `python3 .claude/skills/update-template/update_template.py` (dry run) and `--apply`.

## How local work is protected

For each template file the script compares the project's copy with the template's whole history:

| Result | When | What happens |
| --- | --- | --- |
| `same` | already equal | nothing |
| `add` | new in the template | written |
| `update` | the project's copy equals an earlier template version (never edited here) | replaced |
| `merge` | edited here and changed in the template, on different lines | three-way merged |
| `conflict` | edited here and changed in the template, on the same lines | local copy kept; template's version written next to it as `<file>.template` |
| `keep` | edited here, the template did not change it since | nothing |
| `delete` | the template removed it and it was never edited here | deleted |
| `orphan` | the template removed it but it was edited here | kept |
| `config` | `.claude/project.json` | only keys the template added are filled in; every local value stays |

- Files that exist only in the project are never touched.
- **Project-owned files** (`template.project_owned`, plus the defaults `.claude/project.json`,
  `.claude/skills/request-log/artifact.json`, `.claude/skills/ui-evidence/pages.json`) are never
  overwritten: they hold this project's settings.
- `.claude/settings.local.json` is never taken from the template.
- After `--apply`, `.claude/template-lock.json` records the template commit and its files. The next
  update uses that commit as the merge base, and a template file the project deleted on purpose is
  not added back. Commit the lock with the update.

## Steps

1. Make sure `.claude/` has no uncommitted changes (the script refuses to apply otherwise, so the
   update is one reviewable diff; `--force` overrides).
2. Dry run and show the user the plan:
   `python3 .claude/skills/update-template/update_template.py`
3. Apply: `python3 .claude/skills/update-template/update_template.py --apply`
4. For every `conflict`: compare the file with its `.template` copy, carry the template's change into
   the local file where it fits, then delete the `.template` file. Ask the user when the two
   versions want different things.
5. `orphan` files: tell the user the template no longer has them; delete them only if the user agrees.
6. Review `git diff -- .claude` and summarise the changes for the user: new skills or hooks, changed
   settings, new `project.json` keys they should fill in.
7. Settings and hooks are read when Claude Code starts a session: if `.claude/settings.json` or a hook
   changed, tell the user to restart the session.
8. Commit the update (including `.claude/template-lock.json`) as its own commit, e.g.
   `chore: update .claude from template <short sha>`, and push.
9. Register the project in the projects directory (`.claude/skills/projects-directory/SKILL.md`).

Options: `--repo <url or local path>` and `--branch <name>` override the config (a local path is handy
for testing a template change before pushing it). `--project <dir>` runs the update on another
folder.

## A project without this skill, or a new project

The template's own copy of the script works on any folder:

```bash
git clone --depth 1 https://github.com/spiceroutes/claude_template_request_tasks_and_evidance_html.git /tmp/claude-template
python3 /tmp/claude-template/.claude/skills/update-template/update_template.py --project <dir>          # dry run
python3 /tmp/claude-template/.claude/skills/update-template/update_template.py --project <dir> --apply
```

For a new project that is not a git repo yet, add `--force` (there is nothing to protect). After the
first update the project has this skill and a lock, and later updates run from inside it.

On a fresh install the project-owned files get this project's own values, not the template's:
`artifact.json` is `{"url": null}` (the project gets its own request log on its first publish), and
`project.json` has `app.start`, `app.base_url` and `checks` detected from the project (`start.sh`,
`package.json` scripts and lock file, a `localhost:<port>` in `start.sh`, `package.json`, `.env` or
`vite.config.*`). Every `--apply` also adds the request log's build outputs to `.gitignore` if missing.

A SessionStart hook (`.claude/hooks/template-check.sh`) says at the start of a session when the
template has a newer commit than the lock, and when the project is not in the projects directory
yet (then Claude commits the template files and registers it before the user's first request).

## Automatic install when Claude Code opens (ccyolo)

`attach_template.sh [folder]` installs the template into the folder's git project if it does not
have it yet, uncommitted, and never stops Claude Code from starting. The `ccyolo` and `ccyolot`
functions in `~/.zshrc` run it (from a cached clone at `~/.cache/claude-template`) before Claude
starts. It skips folders outside a git repo, the home folder, projects that already have the
template, the template repo itself, and projects that opt out with a `.claude/no-template` file or
`CLAUDE_TEMPLATE_AUTO=0`. The SessionStart hook then signs the new project up in the directory.

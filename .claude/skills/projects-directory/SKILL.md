---
name: projects-directory
description: Add or refresh this project's row in the Template Projects directory (the shared artifact listing every project that uses this .claude template). Run after every push (task-done does it), after installing or updating the template, and when the user says "register this project", "add this project to the projects directory" or "update the projects directory".
---

# Projects directory

One shared artifact lists every project that uses this template:
**Template Projects** - the URL is in `directory.json` next to this file. Each row: project name,
git repo, local folder, the project's request-log artifact, the last pushed commit and its date and
time, a version number, the `start.sh` (or start command), every `localhost:port` address and every
deployed address.

## Register (or refresh) this project

1. `python3 .claude/skills/projects-directory/register_project.py`
   It prints `{"collection", "doc_id", "data", "directory_url"}`. The values come from
   `.claude/project.json` (`project_name`, `app.start`, `app.base_url`, `app.local_urls`,
   `app.deployed_url` - a string or a list - and `git.remote` / `git.main_branch`), the request log's
   `artifact.json`, `template-lock.json` and git.
2. Write the row with the `ArtifactData` tool (load it with ToolSearch if needed): `action: "get"`
   on `url` = `directory_url`, `collection` = `projects`, `doc_id` = the printed `doc_id`; then
   `action: "set"` with `data` = the printed `data`, passing the read `version` as `if_version` when
   the row exists (omit it for a new project).
3. Tell the user the project's version number and give the directory link.

**Version numbers.** The commit on the remote branch (the last pushed version) at the first
registration is version 1; every registration whose pushed commit is new adds 1. They are kept in
`~/.claude/template-projects.json` on this machine, so registering never creates a commit. Run the
script once per push: registering twice for the same commit does not change the number.

**Missing details.** If the row shows no deployed address, or a local address is missing (an API
port, a second app), ask the user and add it to `.claude/project.json` (`app.deployed_url`,
`app.local_urls`), then register again.

## A new project takes the template

Install with the template's own copy of the update script (it works on any folder):

```bash
python3 <template>/.claude/skills/update-template/update_template.py --project <new project> --apply --force
```

(`--force` only when the new folder is not a git repo yet.) Or run `ccnew` in the new folder: it creates the private GitHub repo, installs and commits the template, pushes, and opens Claude Code to do the registration below (`.claude/skills/update-template/SKILL.md`, *A brand-new project*). Then fill in the new project's
`.claude/project.json`, commit and push, and register it as above, from inside the new project.

Opening Claude Code with `ccyolo` / `ccyolot` in a git project without the template does the
install automatically (`.claude/skills/update-template/attach_template.sh`). Its first session's
SessionStart hook then says the project is not in the directory: commit only the template files
(`git add .claude .gitignore`, "chore: add the .claude template"), push if the branch is level with
its remote, register as above, and tell the user. The hook stays quiet once the project is in the
registry (`~/.claude/template-projects.json`).

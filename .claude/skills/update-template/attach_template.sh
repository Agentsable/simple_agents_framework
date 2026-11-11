#!/usr/bin/env bash
# Install the .claude template into the project a Claude Code session is about to open in, if it
# does not have it yet. Called by the ccyolo / ccyolot shell functions before Claude starts:
#
#   attach_template.sh [folder]        (default: the current folder)
#
# The project is the folder's git top level. Nothing happens (and nothing is fetched) when:
#   - the folder is not in a git repo, or the repo is the home folder
#   - the project already has the template (.claude/template-lock.json or the request-log skill)
#   - the project opts out: a .claude/no-template file, or CLAUDE_TEMPLATE_AUTO=0
#   - the repo is the template itself
# Otherwise update_template.py --apply installs it (project-owned files get this project's own
# values) and leaves it uncommitted. The session's SessionStart hook then asks Claude to commit
# the template files and sign the project up in the projects directory.
# Never fails: Claude Code starts whatever happens here.
TEMPLATE_REPO="${CLAUDE_TEMPLATE_REPO:-https://github.com/spiceroutes/claude_template_request_tasks_and_evidance_html.git}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ "${CLAUDE_TEMPLATE_AUTO:-1}" = "0" ] && exit 0
root=$(git -C "${1:-.}" rev-parse --show-toplevel 2>/dev/null) || exit 0
[ "$root" = "$HOME" ] && exit 0
[ -f "$root/.claude/template-lock.json" ] || [ -f "$root/.claude/skills/request-log/SKILL.md" ] && exit 0
[ -e "$root/.claude/no-template" ] && exit 0
norm() { printf '%s' "$1" | tr 'A-Z' 'a-z' | sed -E 's#(\.git)?/*$##'; }
origin=$(git -C "$root" remote get-url origin 2>/dev/null)
[ -n "$origin" ] && [ "$(norm "$origin")" = "$(norm "$TEMPLATE_REPO")" ] && exit 0

echo "Template: $root has no .claude template; installing it (opt out: touch .claude/no-template)."
out=$(GIT_TERMINAL_PROMPT=0 python3 "$HERE/update_template.py" --project "$root" --repo "$TEMPLATE_REPO" --apply 2>&1)
status=$?
printf '%s\n' "$out" | grep -E '^(summary|template commit|applied|conflicts|Commit or stash)' | sed 's/^/  /'
if [ $status -ne 0 ]; then
  echo "  not installed: $(printf '%s\n' "$out" | tail -1)"
else
  echo "  installed, uncommitted. The session will commit it and sign the project up in the projects directory."
fi
exit 0

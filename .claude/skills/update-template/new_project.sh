#!/usr/bin/env bash
# Start a new project from the current folder: a private GitHub repo <org>/<folder name>, the .claude
# template installed and committed, pushed, then Claude Code opened to finish the initialization
# (sign the project up in the Template Projects directory). Run it as `ccnew` from the new folder:
#
#   ccnew [-r|--org <org>] [--name <repo name>] [--source <template folder>] [--no-claude] [--dry-run]
#
#   -r, --org    GitHub organization (default: spiceroutes, or $CCNEW_ORG), e.g. ccnew -r agentsable
#   --name       repo name (default: the folder name; spaces become dashes)
#   --source     install the template from this local template checkout instead of the cached clone
#                of the template repo (~/.cache/claude-template, the one ccyolo uses)
#   --no-claude  stop after the push; open Claude Code yourself later (ccyolo) to finish
#   --dry-run    check everything and print the plan; change nothing
#
# The folder may be empty or hold files already, and may be a git repo without a remote. Refused:
# the home folder, a subfolder of another git repo, a repo that already has an `origin`, and a
# GitHub repo that already exists. Safe to run again after a failure: done steps are skipped.
# Needs git, python3 and an authenticated gh (gh auth login).
set -euo pipefail

TEMPLATE_REPO="${CLAUDE_TEMPLATE_REPO:-https://github.com/spiceroutes/claude_template_request_tasks_and_evidance_html.git}"
CACHE="${CLAUDE_TEMPLATE_CACHE:-$HOME/.cache/claude-template}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
org="${CCNEW_ORG:-spiceroutes}"; name=""; source=""; launch=1; dry=0

die() { echo "ccnew: $*" >&2; exit 1; }
step() { echo "==> $*"; }
usage() { sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    -r|--org) org="${2:?-r/--org needs an organization}"; shift 2 ;;
    --name) name="${2:?--name needs a value}"; shift 2 ;;
    --source) source="${2:?--source needs a folder}"; shift 2 ;;
    --no-claude) launch=0; shift ;;
    --dry-run) dry=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (see ccnew --help)" ;;
  esac
done

dir="$(pwd -P)"
[ "$dir" = "$(cd "$HOME" && pwd -P)" ] && die "run it from the new project's folder, not the home folder"
[ -n "$name" ] || name="$(basename "$dir" | tr ' ' '-')"
[[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || die "'$name' is not a valid GitHub repo name (letters, digits, . _ -); pass --name"
full="$org/$name"

norm() { printf '%s' "$1" | tr 'A-Z' 'a-z' | sed -E 's#(\.git)?/*$##'; }
top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$top" ] && top="$(cd "$top" && pwd -P)"
if [ -n "$top" ] && [ "$top" != "$dir" ]; then
  die "$dir is inside the git repo $top; run ccnew from a folder of its own"
fi
if [ -n "$top" ] && origin="$(git -C "$dir" remote get-url origin 2>/dev/null)"; then
  [ "$(norm "$origin")" = "$(norm "$TEMPLATE_REPO")" ] && die "this is the template repo itself"
  die "this repo already has a remote: origin = $origin"
fi

command -v git >/dev/null || die "git is not installed"
command -v python3 >/dev/null || die "python3 is not installed"
command -v gh >/dev/null || die "gh is not installed (brew install gh)"
gh auth status >/dev/null 2>&1 || die "gh is not logged in: run gh auth login"
if gh repo view "$full" >/dev/null 2>&1; then
  die "github.com/$full already exists; pick another name with --name, or clone it instead"
fi

# The template to install: --source, else the cached clone of the template repo.
if [ -z "$source" ]; then
  source="$CACHE"
  here_top="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)"
  if [ "$dry" = 1 ]; then
    :
  elif [ -n "$here_top" ] && [ "$(cd "$here_top" && pwd -P)" = "$(mkdir -p "$CACHE" && cd "$CACHE" && pwd -P)" ]; then
    :  # running from the cache: the ccnew command refreshed it just before
  elif [ -d "$CACHE/.git" ]; then
    GIT_TERMINAL_PROMPT=0 git -C "$CACHE" pull -q --ff-only || echo "ccnew: could not update $CACHE; using it as it is" >&2
  else
    rmdir "$CACHE" 2>/dev/null || true
    GIT_TERMINAL_PROMPT=0 git clone -q "$TEMPLATE_REPO" "$CACHE" || die "could not clone the template from $TEMPLATE_REPO"
  fi
fi
if [ -d "$source" ]; then
  source="$(cd "$source" && pwd -P)"
  [ -f "$source/.claude/skills/update-template/update_template.py" ] || die "$source has no update_template.py: is it the template repo?"
elif [ "$dry" = 0 ] || [ "$source" != "$CACHE" ]; then
  die "--source $source: no such folder"
fi

has_template=0
[ -f "$dir/.claude/template-lock.json" ] || [ -f "$dir/.claude/skills/request-log/SKILL.md" ] && has_template=1

if [ "$dry" = 1 ]; then
  echo "ccnew dry run in $dir - nothing changed."
  echo "  repo:      github.com/$full (private; does not exist yet)"
  echo "  git:       $([ -n "$top" ] && echo "existing repo, branch $(git -C "$dir" branch --show-current)" || echo "git init (branch main)")"
  echo "  template:  $([ "$has_template" = 1 ] && echo "already installed" || echo "install from $source")"
  echo "  commit:    $(ls -A "$dir" | grep -vx .git | wc -l | tr -d ' ') existing item(s) in the folder, plus the template"
  echo "  then:      push to origin; $([ "$launch" = 1 ] && echo "open Claude Code to register it in the projects directory" || echo "stop (--no-claude)")"
  exit 0
fi

if [ -z "$top" ]; then
  step "git init (branch main)"
  git -C "$dir" init -q -b main
fi

if [ "$has_template" = 0 ]; then
  step "installing the .claude template from $source"
  out="$(python3 "$source/.claude/skills/update-template/update_template.py" --project "$dir" \
    --repo "$TEMPLATE_REPO" --source "$source" --apply --force 2>&1)" || die "template install failed:
$out"
  printf '%s\n' "$out" | grep -E '^(template commit|summary|applied)' | sed 's/^/    /' || true
else
  step "the .claude template is already installed"
fi

[ -x "$HOME/ensure_ignores.sh" ] && (cd "$dir" && "$HOME/ensure_ignores.sh" >/dev/null)
if [ -z "$(ls -A "$dir" | grep -vE '^(\.git|\.claude|\.gitignore|\.claudeignore|\.cursorignore)$' || true)" ] && [ ! -e "$dir/README.md" ]; then
  printf '# %s\n' "$name" > "$dir/README.md"
fi

git -C "$dir" add -A
if ! git -C "$dir" diff --cached --quiet; then
  step "committing $(git -C "$dir" diff --cached --name-only | wc -l | tr -d ' ') file(s)"
  git -C "$dir" commit -q -m "chore: start $name with the .claude template" \
    -m "Created by ccnew: private repo github.com/$full, template from $TEMPLATE_REPO."
fi

step "creating the private repo github.com/$full and pushing"
gh repo create "$full" --private --source "$dir" --remote origin --push >/dev/null
echo "    https://github.com/$full"

prompt="This project was just created by ccnew (private repo github.com/$full, .claude template installed, committed and pushed). Finish its initialization: register it in the Template Projects directory (.claude/skills/projects-directory/SKILL.md), fill app.start and app.base_url in .claude/project.json if the project already shows them, and give me the directory link."
if [ "$launch" = 0 ]; then
  step "done. Open Claude Code here (ccyolo) to register the project in the projects directory."
  exit 0
fi
step "opening Claude Code to register the project in the projects directory"
launcher="${CCNEW_LAUNCHER:-ccyolo}"
cd "$dir"
if [ "$launcher" != claude ] && command -v zsh >/dev/null && zsh -ic "whence $launcher" >/dev/null 2>&1; then
  exec zsh -ic "$launcher \"\$1\"" ccnew "$prompt"
fi
command -v claude >/dev/null || die "claude is not installed; the repo is ready, register it from a Claude Code session"
exec claude "$prompt"

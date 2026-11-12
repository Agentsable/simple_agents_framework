"""colab_demo.ipynb as a flat script — same cells, same order, same text.

Each notebook cell is marked `## <its name>`; markdown cells keep their prose as
comments under the marker. Run it top to bottom:

    python3 colab_demo.py

ponytail: three deviations from the notebook, all forced by "not a notebook":
the `%pip` magic is a comment, answers are printed instead of streamed as HTML,
and the key can also come from `.env`.
"""

import os

## simple_agents_framework on Colab
# Markdown file in, callable agent out. Run the cells top to bottom.
#
# Repo: https://github.com/Agentsable/simple_agents_framework

## 1. Install
# The `claude` CLI the SDK shells out to is bundled in the pip package, so this is
# the only install step.
#
#   pip install -q git+https://github.com/Agentsable/simple_agents_framework.git
#
# ponytail: a comment, not a call — a script can't run the notebook's `%pip` magic,
# and reinstalling on every run is what made it a one-time cell in the first place.

## 2. API key
# Paste it below, or leave it blank to fall back to .env / the environment / a prompt.
import getpass

ENV_FILE = '.env' if os.path.exists('.env') else None
API_KEY = ''.strip() or os.environ.get('ANTHROPIC_API_KEY') or None
if not API_KEY and not ENV_FILE:
    API_KEY = getpass.getpass('Anthropic API key: ')
if API_KEY:
    assert API_KEY.startswith('sk-'), 'that does not look like an API key'

## 3. Define an agent
# Frontmatter configures it, the body is the system prompt. `permission_mode: acceptEdits`
# is needed on Colab: Colab runs as root, and the CLI refuses `bypassPermissions` there.
from pathlib import Path

Path('doc_reader.md').write_text('''---
name: doc_reader
model: claude-sonnet-5-5
tools: Read, Grep, Glob
permission_mode: acceptEdits
---
You answer questions about the files in this folder.

- Glob/Grep to find the relevant files and Read them before answering. Never guess.
- At most 6 bullets, one sentence each, citing locations as `file:line`.
''')

## 4. Ask it something
# `stream=html_stream` renders the run live: blue sent, green agent, amber tool call,
# cyan tool result. Drop `stream=` to just get the string back.
import simple_agents_framework as saf

WORKDIR = '/content' if os.path.isdir('/content') else '.'  # Colab, or wherever you run it
agent = saf.create_agent_from_markdown('doc_reader.md', API_KEY, env_file=ENV_FILE, cwd=WORKDIR)
print(agent.ask('What files are in this folder, and what is each one for?'))

## 5. Follow up
# Follow-ups resume the same session, so context carries over.
print(agent.ask('Which of those changed most recently?'))

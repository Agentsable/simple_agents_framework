# simple_agents_framework

A markdown file in, a callable agent out. One Python file over the
[Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).

```python
import simple_agents_framework as saf

agent = saf.create_agent_from_markdown("doc_reader.md", API_KEY)
agent.ask("which markdown files are here?")   # -> str
agent.ask_html("...")                         # same, streamed as HTML in Jupyter
```

## Agent files

Frontmatter configures, body is the system prompt. Every key is optional:

| key | effect |
|---|---|
| `name` | agent name (defaults to the filename) |
| `model` | e.g. `claude-sonnet-5` |
| `tools` | comma-separated allowlist, e.g. `Read, Grep, Glob` |
| `permission_mode` | defaults to `bypassPermissions` — headless agents can't answer prompts |

Anything else passes through as a `ClaudeAgentOptions` kwarg:
`create_agent_from_markdown(path, key, cwd="/repo", max_turns=5)`.

## API

- `ask(prompt) -> str` — blocks, works inside Jupyter too.
- `ask_html(prompt) -> str` — same run, streamed into the cell: blue sent,
  green agent, slate thinking, amber tool call, cyan tool result, red error.
  The agent's text fills in token by token; tool calls and results appear whole.
- `ask_async(prompt, on_event=None)` — `on_event(kind, title, body, replace)`
  per update. `replace=True` means "same block, more text": redraw the last
  thing you drew instead of appending. Build your own renderer on this.

Follow-up asks resume the previous session, so context carries over.

## Files

- `simple_agents_framework.py` — the whole thing. `python simple_agents_framework.py` runs its self-check.
- `doc_reader.md` — example agent: reads the markdown in a project and answers questions about it.
- `demo.ipynb` — end-to-end walkthrough with streamed output.

## Gotcha

The SDK spawns whatever `claude` is first on `PATH`. Some tools install a
wrapper there that never returns headlessly — if `ask()` hangs, pass
`cli_path=Path.home() / ".local/bin/claude"`.

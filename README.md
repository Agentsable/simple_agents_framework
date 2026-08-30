# simple_agents_framework

A markdown file in, a callable agent out. One Python file over the
[Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).

```python
import simple_agents_framework as saf

agent = saf.create_agent_from_markdown("doc_reader.md", API_KEY)
agent.ask("which markdown files are here?")            # -> str
agent.ask("...", stream=saf.text_stream)               # same, streamed to stdout

from plugins.streaming.jupyter_html import html_stream
agent.ask("...", stream=html_stream)                   # streamed as HTML in Jupyter
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

- `ask(prompt, stream=None) -> str` — blocks, works inside Jupyter too.
  `stream` is an output plugin; `None` renders nothing.
- `ask_async(prompt, stream=None, on_event=None)` — same, awaitable.
  `on_event` is the raw callback if you don't want a plugin's setup/teardown.

## Output plugins

An output plugin is `stream(prompt)` -> context manager yielding
`emit(kind, title, body, replace)`. `kind` is one of `sent`, `received`,
`thinking`, `tool use`, `tool result`, `error`. `replace=True` means "same
block, more text": redraw the last thing you drew instead of appending.

The framework ships one default and imports no plugin:

- `saf.text_stream` — built in, plain text to stdout.
- `plugins/streaming/jupyter_html.py` → `html_stream` — color-coded cards in a
  Jupyter cell: blue sent, green agent, slate thinking, amber tool call, cyan
  tool result, red error. The agent's text fills in token by token.

Writing your own is ~10 lines — copy `text_stream` and drop it in
`plugins/streaming/`.

Follow-up asks resume the previous session, so context carries over.

## Files

- `simple_agents_framework.py` — the whole framework, plugin-free. `python simple_agents_framework.py` runs its self-check.
- `plugins/streaming/` — output plugins. Each file runs its own self-check the same way.
- `doc_reader.md` — example agent: reads the markdown in a project and answers questions about it.
- `demo.ipynb` — end-to-end walkthrough with streamed output.

## Gotcha

The SDK spawns whatever `claude` is first on `PATH`. Some tools install a
wrapper there that never returns headlessly — if `ask()` hangs, pass
`cli_path=Path.home() / ".local/bin/claude"`.

## License

MIT — see `LICENSE`.

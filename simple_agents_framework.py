"""Markdown-defined agents on top of the Claude Agent SDK.

    import simple_agents_framework as saf
    from plugins.streaming.jupyter_html import html_stream

    agent = saf.create_agent_from_markdown("researcher.md", anthropic_api_key)
    agent.ask("what changed today?", stream=html_stream)   # or drop stream=

Credentials can come from a `.env` file instead of an argument:

    agent = saf.create_agent_from_markdown("researcher.md", env_file=".env")

If that file defines all four of LLM_URL / LLM_FORMAT / LLM_API_KEY /
LLM_MODEL, the agent talks to that endpoint; otherwise it falls back to
ANTHROPIC_API_KEY from the same file.

Markdown file = optional `key: value` frontmatter + body (the system prompt):

    ---
    name: researcher
    model: claude-opus-5-5
    base_url: https://my-proxy.example.com   # optional; defaults to Anthropic
    tools: Read, Grep, Glob
    ---
    You are a careful code researcher.

A streaming plugin is `stream(prompt)` -> context manager yielding
`emit(kind, title, body, replace)`. `kind` is one of sent / received /
thinking / tool use / tool result / error. `replace=True` means "same block,
more text".
"""

import asyncio
import json
import os
import re
import threading
from contextlib import nullcontext
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

__all__ = ["Agent", "create_agent_from_markdown"]

_loop = None


def _run(coro):
    """Run a coroutine on one shared background loop, from sync code.

    ponytail: a background loop rather than asyncio.run per call — that blows
    up inside Jupyter, which already owns the main loop.
    """
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
        threading.Thread(target=_loop.run_forever, daemon=True).start()
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


def _clip(text, limit=1200):
    if isinstance(text, list):  # tool results arrive as content blocks
        text = "\n".join(b.get("text", str(b)) if isinstance(b, dict) else str(b) for b in text)
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit] + f"\n… (+{len(text) - limit} chars)"


def _parse_markdown(text):
    """-> (metadata dict, system prompt). Frontmatter is flat `key: value` lines."""
    meta, body = {}, text
    if text.lstrip().startswith("---"):
        _, front, body = text.lstrip().split("---", 2)
        meta = {k: v.strip() for k, v in re.findall(r"^(\w+)\s*:\s*(.*)$", front, re.M)}
    return meta, body.strip()


# ponytail: the SDK speaks Anthropic's Messages format, so a proxy must too.
# Widen this set (and the translation) only when a proxy actually needs it.
_ANTHROPIC_FORMATS = {"anthropic", "claude", "anthropic-messages", "messages"}

_LLM_KEYS = ("LLM_URL", "LLM_FORMAT", "LLM_API_KEY", "LLM_MODEL")


def _read_env_file(path):
    """-> dict of `KEY=value` lines. Blank lines, `#` comments and `export `
    prefixes are skipped; surrounding quotes are stripped.

    ponytail: 10 lines of str.split beats a dependency for KEY=value.
    """
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


class Agent:
    def __init__(self, name, options):
        self.name = name
        self.options = options

    def ask(self, prompt, stream=None):
        """Send a prompt, return the agent's final text. Blocks until done."""
        return _run(self.ask_async(prompt, stream))

    async def ask_async(self, prompt, stream=None):
        """Async `ask`. `stream` is a plugin (see the module docstring)."""
        with (stream(prompt) if stream else nullcontext()) as emit:
            return await self._run_query(prompt, emit or (lambda *a: None))

    async def _run_query(self, prompt, emit):
        text, buf = [], ""
        async for message in query(prompt=prompt, options=self.options):
            if isinstance(message, StreamEvent):
                event = message.event
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    chunk = delta.get("text") or delta.get("thinking") or ""
                    if chunk:  # tool-input deltas have neither; they land whole below
                        buf += chunk
                        thinking = delta.get("type") == "thinking_delta"
                        emit(*(("thinking", "thinking") if thinking
                               else ("received", self.name)), buf, True)
                elif event.get("type") == "content_block_stop":
                    buf = ""
                continue
            for block in getattr(message, "content", []) or []:
                if isinstance(block, TextBlock) and isinstance(message, AssistantMessage):
                    text.append(block.text)  # already streamed in above, token by token
                elif isinstance(block, ToolUseBlock):
                    emit("tool use", block.name, _clip(json.dumps(block.input, indent=2)), False)
                elif isinstance(block, ToolResultBlock):
                    kind = "error" if block.is_error else "tool result"
                    emit(kind, kind, _clip(block.content), False)
            if isinstance(message, ResultMessage):
                # ponytail: resuming the session is how follow-up asks keep context.
                if message.session_id:
                    self.options.resume = message.session_id
                if message.is_error:  # e.g. "API Error: 400 …" — don't hand it back as an answer
                    raise RuntimeError(message.result or message.errors or message.subtype)
                if message.result:
                    return message.result
        return "\n".join(text)

    def __repr__(self):
        return f"<Agent {self.name!r}>"


def create_agent_from_markdown(markdown_file_path, anthropic_api_key=None,
                               base_url=None, model=None, env_file=None, **overrides):
    """Build an Agent from a markdown file. Extra kwargs go to ClaudeAgentOptions.

    `base_url` points the SDK at a proxy / gateway instead of api.anthropic.com;
    `model` overrides the frontmatter. Both also readable from frontmatter
    (`base_url:` / `model:`); the argument wins.

    `env_file` is a path to a `.env`. If it defines all four of LLM_URL,
    LLM_FORMAT, LLM_API_KEY and LLM_MODEL, those four are loaded into the
    agent's environment and supply url / key / model. Otherwise the file's
    ANTHROPIC_API_KEY is used. Precedence: argument > .env > ambient environment.
    """
    path = Path(markdown_file_path)
    meta, system_prompt = _parse_markdown(path.read_text(encoding="utf-8"))

    env = dict(os.environ)
    file_env = _read_env_file(env_file) if env_file else {}

    llm = {k: file_env.get(k) for k in _LLM_KEYS}
    if all(llm.values()):
        fmt = llm["LLM_FORMAT"].strip().lower()
        if fmt not in _ANTHROPIC_FORMATS:
            raise ValueError(f"LLM_FORMAT={llm['LLM_FORMAT']!r} is not supported; "
                             f"the SDK speaks the Anthropic Messages format "
                             f"(one of {sorted(_ANTHROPIC_FORMATS)})")
        env.update(llm)  # pass the four through, for proxies that read them
        anthropic_api_key = anthropic_api_key or llm["LLM_API_KEY"]
        base_url = base_url or llm["LLM_URL"]
        model = model or llm["LLM_MODEL"]
    elif any(llm.values()):
        missing = [k for k, v in llm.items() if not v]
        raise ValueError(f"{env_file}: partial LLM config — missing {', '.join(missing)}. "
                         f"Set all of {', '.join(_LLM_KEYS)} or none of them.")

    anthropic_api_key = anthropic_api_key or file_env.get("ANTHROPIC_API_KEY")
    if anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = anthropic_api_key
    elif "ANTHROPIC_API_KEY" not in env:
        raise ValueError("no API key: pass anthropic_api_key, point env_file at a "
                         ".env holding ANTHROPIC_API_KEY or the four LLM_* keys, "
                         "or set ANTHROPIC_API_KEY in the environment")

    base_url = base_url or meta.get("base_url")
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url.rstrip("/")

    opts = dict(
        system_prompt=system_prompt,
        env=env,
        # ponytail: headless agents can't answer permission prompts. Colab runs
        # as root, where the CLI refuses bypass — set permission_mode there.
        permission_mode=meta.get("permission_mode", "bypassPermissions"),
        include_partial_messages=True,  # what makes streams fill in word by word
    )
    if model or "model" in meta:
        opts["model"] = model or meta["model"]
    if "tools" in meta:
        # `tools` limits what the agent has; `allowed_tools` alone only skips prompts.
        opts["tools"] = opts["allowed_tools"] = [t.strip() for t in meta["tools"].split(",") if t.strip()]
    opts.update(overrides)

    return Agent(meta.get("name", path.stem), ClaudeAgentOptions(**opts))

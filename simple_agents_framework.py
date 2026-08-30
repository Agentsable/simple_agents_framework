"""Markdown-defined agents on top of the Claude Agent SDK.

    import simple_agents_framework as saf
    agent = saf.create_agent_from_markdown("researcher.md", anthropic_api_key)
    print(agent.ask("what changed in the repo today?"))

Pass `stream=` to watch the run as it happens. The built-in `text_stream`
writes to stdout; richer renderers live in `plugins/streaming/` and this
module never imports them:

    agent.ask("...", stream=saf.text_stream)                  # built in
    from plugins.streaming.jupyter_html import html_stream    # plugin
    agent.ask("...", stream=html_stream)

A streaming plugin is `stream(prompt)` -> context manager yielding
`emit(kind, title, body, replace)`. `kind` is one of sent / received /
thinking / tool use / tool result / error. `replace=True` means "same block,
more text": redraw what you last drew instead of appending.

Markdown file = optional YAML-ish frontmatter + body (the system prompt):

    ---
    name: researcher
    description: digs through code
    model: claude-opus-5
    tools: Read, Grep, Glob
    ---
    You are a careful code researcher. Answer with file:line references.
"""

import asyncio
import json
import os
import re
import sys
import threading
from contextlib import contextmanager, nullcontext
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    StreamEvent,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

__all__ = ["Agent", "create_agent_from_markdown", "text_stream"]


_loop = None


def _run(coro):
    """Run a coroutine on one shared background loop, from sync code.

    ponytail: a background loop rather than asyncio.run per call — that closes
    the child-process watcher every time (noisy warnings) and blows up inside
    Jupyter, which already owns the main loop.
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


@contextmanager
def text_stream(prompt, file=None):
    """Default output stream: plain text to stdout, no dependencies.

    ponytail: `replace=True` bodies are cumulative, so print only the new tail
    rather than redrawing — a terminal can't take a card back.
    """
    out = file or sys.stdout
    print(f"\n> {prompt}\n", file=out, flush=True)
    shown = [""]  # how much of the currently open block is already on screen

    def emit(kind, title, body, replace):
        if replace:
            if body.startswith(shown[0]):
                body = body[len(shown[0]):]
            shown[0] += body
            print(body, end="", file=out, flush=True)
            return
        if shown[0]:
            print(file=out)
            shown[0] = ""
        if kind == "received":
            print(body, file=out, flush=True)
        else:
            print(f"[{title}] {body}", file=out, flush=True)

    try:
        yield emit
    finally:
        if shown[0]:
            print(file=out, flush=True)


def _parse_markdown(text):
    """-> (metadata dict, system prompt). Frontmatter is flat `key: value` lines."""
    meta, body = {}, text
    if text.lstrip().startswith("---"):
        _, front, body = text.lstrip().split("---", 2)
        meta = {k: v.strip() for k, v in re.findall(r"^(\w+)\s*:\s*(.*)$", front, re.M)}
    return meta, body.strip()


class Agent:
    def __init__(self, name, options):
        self.name = name
        self.options = options

    def ask(self, prompt, stream=None):
        """Send a prompt, return the agent's final text. Blocks until done.

        stream: a streaming plugin, e.g. `text_stream`. None renders nothing.
        """
        return _run(self.ask_async(prompt, stream))

    async def ask_async(self, prompt, stream=None, on_event=None):
        """Run the prompt. `stream` is a plugin; `on_event(kind, title, body,
        replace)` is the same contract without the setup/teardown."""
        with (stream(prompt) if stream else nullcontext(on_event)) as emit:
            return await self._run_query(prompt, emit or (lambda *a: None))

    async def _run_query(self, prompt, emit):
        partial = self.options.include_partial_messages
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
                if isinstance(block, TextBlock):
                    if isinstance(message, AssistantMessage):
                        text.append(block.text)
                        if not partial:  # else it already streamed in, token by token
                            emit("received", self.name, block.text, False)
                elif isinstance(block, ThinkingBlock):
                    if not partial:
                        emit("thinking", "thinking", _clip(block.thinking), False)
                elif isinstance(block, ToolUseBlock):
                    emit("tool use", block.name, _clip(json.dumps(block.input, indent=2)), False)
                elif isinstance(block, ToolResultBlock):
                    kind = "error" if block.is_error else "tool result"
                    emit(kind, kind, _clip(block.content), False)
            if isinstance(message, ResultMessage):
                # ponytail: resuming the session is how follow-up asks keep context.
                # Drop these two lines if you want every ask() stateless.
                if message.session_id:
                    self.options.resume = message.session_id
                if message.result:
                    return message.result
        return "\n".join(text)

    def __repr__(self):
        return f"<Agent {self.name!r}>"


def create_agent_from_markdown(markdown_file_path, anthropic_api_key=None, **overrides):
    """Build an Agent from a markdown file. Extra kwargs go to ClaudeAgentOptions."""
    path = Path(markdown_file_path)
    meta, system_prompt = _parse_markdown(path.read_text(encoding="utf-8"))

    env = dict(os.environ)
    if anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = anthropic_api_key
    elif "ANTHROPIC_API_KEY" not in env:
        raise ValueError("no anthropic_api_key given and ANTHROPIC_API_KEY is unset")

    opts = dict(
        system_prompt=system_prompt,
        env=env,
        # ponytail: headless agents can't answer permission prompts. Pass
        # permission_mode="acceptEdits" (or "plan") if bypass is too much.
        permission_mode=meta.get("permission_mode", "bypassPermissions"),
        # ponytail: always on rather than a flag — the extra pipe traffic is
        # cheap and it's what makes streams fill in word by word.
        include_partial_messages=True,
    )
    if "model" in meta:
        opts["model"] = meta["model"]
    if "tools" in meta:
        opts["allowed_tools"] = [t.strip() for t in meta["tools"].split(",") if t.strip()]
    opts.update(overrides)

    return Agent(meta.get("name", path.stem), ClaudeAgentOptions(**opts))


if __name__ == "__main__":
    import io

    meta, body = _parse_markdown(
        "---\nname: bob\ntools: Read, Grep\n---\nYou are bob.\n\n---\nnot frontmatter\n"
    )
    assert meta == {"name": "bob", "tools": "Read, Grep"}, meta
    assert body == "You are bob.\n\n---\nnot frontmatter", repr(body)

    meta, body = _parse_markdown("Just a prompt.")
    assert meta == {} and body == "Just a prompt."

    # default stream: cumulative deltas print once, whole blocks get a label.
    sink = io.StringIO()
    with text_stream("hi", file=sink) as emit:
        emit("received", "bob", "Hel", True)
        emit("received", "bob", "Hello", True)
        emit("tool use", "Read", "{}", False)
    assert sink.getvalue() == "\n> hi\n\nHello\n[Read] {}\n", repr(sink.getvalue())

    tmp = Path("_saf_selfcheck.md")
    tmp.write_text("---\nname: bob\nmodel: claude-opus-5\ntools: Read\n---\nYou are bob.")
    try:
        a = create_agent_from_markdown(tmp, "sk-test")
        assert a.name == "bob" and a.options.model == "claude-opus-5"
        assert a.options.allowed_tools == ["Read"]
        assert a.options.env["ANTHROPIC_API_KEY"] == "sk-test"
        assert a.options.include_partial_messages is True

        # token streaming: deltas redraw one block, the finished block must not
        # emit a second copy of the same text.
        import claude_agent_sdk as _sdk

        async def fake_query(prompt, options):
            for chunk in ("Hel", "lo ", "there"):
                yield _sdk.StreamEvent(uuid="u", session_id="s", event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": chunk}})
            yield _sdk.StreamEvent(uuid="u", session_id="s",
                                   event={"type": "content_block_stop"})
            yield AssistantMessage(content=[TextBlock("Hello there")], model="m")
            yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                                is_error=False, num_turns=1, session_id="sess-1",
                                result="Hello there")

        global query
        query, seen = fake_query, []
        out = _run(a.ask_async("hi", on_event=lambda *e: seen.append(e)))
        assert out == "Hello there", out
        assert [e[2] for e in seen] == ["Hel", "Hello ", "Hello there"], seen
        assert all(e[3] for e in seen), "deltas must be replace=True"
        assert a.options.resume == "sess-1"

        # a plugin is just a context manager; ask() drives it end to end.
        sink = io.StringIO()
        assert a.ask("hi", stream=lambda p: text_stream(p, file=sink)) == "Hello there"
        assert sink.getvalue() == "\n> hi\n\nHello there\n", repr(sink.getvalue())
    finally:
        tmp.unlink()
    print("ok")

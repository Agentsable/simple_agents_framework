"""Streaming plugin: render a run as color-coded HTML in a Jupyter cell.

    from plugins.streaming.jupyter_html import html_stream
    agent.ask("what changed today?", stream=html_stream)

Blue sent, green agent, slate thinking, amber tool call, cyan tool result,
red error. The agent's text fills in token by token.
"""

import html
import time
from contextlib import contextmanager

__all__ = ["html_stream", "COLORS"]

# label -> accent color, one per kind of thing that shows up in a run.
COLORS = {
    "sent": "#2563eb",         # blue  - what you sent
    "received": "#16a34a",     # green - what the agent said
    "thinking": "#64748b",     # slate - reasoning
    "tool use": "#d97706",     # amber - tool call
    "tool result": "#0891b2",  # cyan  - tool output
    "error": "#dc2626",        # red
}


def _card(kind, title, body):
    color = COLORS.get(kind, COLORS["received"])
    return (
        f'<div style="border-left:3px solid {color};background:{color}14;'
        'padding:6px 10px;margin:4px 0;border-radius:0 4px 4px 0;'
        'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px">'
        f'<div style="color:{color};font-weight:600;letter-spacing:.04em;'
        f'text-transform:uppercase;font-size:10.5px">{html.escape(title)}</div>'
        f'<div style="white-space:pre-wrap;color:inherit;opacity:.9">{html.escape(body)}</div>'
        "</div>"
    )


@contextmanager
def html_stream(prompt):
    from IPython.display import HTML, display

    cards = [_card("sent", "sent", prompt)]
    handle = display(HTML("".join(cards)), display_id=True)
    state = {"open": False, "drawn": 0.0}

    def flush(force=False):
        # ponytail: ~20fps. Every token would be its own display update, each
        # re-joining the whole card list. force=True on the last draw.
        if force or time.monotonic() - state["drawn"] > 0.05:
            state["drawn"] = time.monotonic()
            handle.update(HTML("".join(cards)))

    def emit(kind, title, body, replace):
        card = _card(kind, title, body)
        if replace and state["open"]:
            cards[-1] = card
        else:
            cards.append(card)
        state["open"] = replace
        flush(force=not replace)

    try:
        yield emit
    finally:
        flush(force=True)  # the throttle may have skipped the last tokens


if __name__ == "__main__":
    seen = []

    class _Handle:
        def update(self, obj):
            seen.append(obj.data)

    import sys
    import types

    fake = types.ModuleType("IPython.display")
    fake.HTML = lambda data: types.SimpleNamespace(data=data)
    fake.display = lambda obj, display_id=None: _Handle()
    sys.modules["IPython"] = types.ModuleType("IPython")
    sys.modules["IPython.display"] = fake

    with html_stream("hi") as emit:
        emit("received", "bob", "Hel", True)
        emit("received", "bob", "Hello", True)   # replaces, does not append
        emit("tool use", "Read", "{}", False)

    final = seen[-1]
    assert final.count("<div style=\"border-left") == 3, final  # sent + text + tool
    assert "Hello" in final and ">Hel<" not in final, final
    assert "&lt;script&gt;" in _card("sent", "sent", "<script>")
    print("ok")

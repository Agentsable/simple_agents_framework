"""Streaming plugins: context managers that render a run as it happens.

    from plugins.streaming.jupyter_html import html_stream
    agent.ask("hi", stream=html_stream)

A streaming plugin is `stream(prompt)` -> context manager yielding
`emit(kind, title, body, replace)`. See jupyter_html.py for an example.
"""

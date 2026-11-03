"""ponytail: one check for the .env + LLM_* precedence logic. `python test_env_file.py`."""
import os
import tempfile
from pathlib import Path

os.environ.pop("ANTHROPIC_BASE_URL", None)
os.environ["ANTHROPIC_API_KEY"] = "sk-ambient"

import simple_agents_framework as saf

TMP = Path(tempfile.mkdtemp())
MD = TMP / "a.md"
MD.write_text("---\nname: a\n---\nhi")


def env_file(text):
    p = TMP / "env"
    p.write_text(text)
    return p


def test_reader_handles_comments_quotes_and_export():
    got = saf._read_env_file(env_file(
        '# comment\n\nexport A=1\nB="two"\nC=\'three\'\nD=4 # trailing\nnot_a_pair\n'))
    assert got == {"A": "1", "B": "two", "C": "three", "D": "4"}, got


def test_all_four_llm_keys_are_used_and_exported():
    agent = saf.create_agent_from_markdown(MD, env_file=env_file(
        "LLM_URL=https://proxy.example.com/\nLLM_FORMAT=anthropic\n"
        "LLM_API_KEY=sk-proxy\nLLM_MODEL=claude-opus-5-5\n"))
    env = agent.options.env
    assert agent.options.model == "claude-opus-5-5"
    assert env["ANTHROPIC_BASE_URL"] == "https://proxy.example.com"
    assert env["ANTHROPIC_API_KEY"] == "sk-proxy"
    assert env["LLM_FORMAT"] == "anthropic" and env["LLM_URL"] == "https://proxy.example.com/"


def test_arguments_beat_the_env_file():
    agent = saf.create_agent_from_markdown(MD, "sk-arg", base_url="https://arg.example.com",
                                           model="claude-sonnet-5-5", env_file=env_file(
        "LLM_URL=https://proxy.example.com\nLLM_FORMAT=anthropic\n"
        "LLM_API_KEY=sk-proxy\nLLM_MODEL=claude-opus-5-5\n"))
    assert agent.options.model == "claude-sonnet-5-5"
    assert agent.options.env["ANTHROPIC_API_KEY"] == "sk-arg"
    assert agent.options.env["ANTHROPIC_BASE_URL"] == "https://arg.example.com"


def test_falls_back_to_anthropic_key_in_the_file():
    agent = saf.create_agent_from_markdown(MD, env_file=env_file("ANTHROPIC_API_KEY=sk-file\n"))
    assert agent.options.env["ANTHROPIC_API_KEY"] == "sk-file"
    assert "ANTHROPIC_BASE_URL" not in agent.options.env


def test_partial_llm_config_is_an_error():
    try:
        saf.create_agent_from_markdown(MD, env_file=env_file(
            "LLM_URL=https://proxy.example.com\nLLM_API_KEY=sk-proxy\n"))
    except ValueError as exc:
        assert "LLM_FORMAT" in str(exc) and "LLM_MODEL" in str(exc), exc
    else:
        raise AssertionError("partial LLM_* config should raise")


def test_non_anthropic_format_is_an_error():
    try:
        saf.create_agent_from_markdown(MD, env_file=env_file(
            "LLM_URL=https://proxy.example.com\nLLM_FORMAT=openai\n"
            "LLM_API_KEY=sk-proxy\nLLM_MODEL=gpt-5\n"))
    except ValueError as exc:
        assert "LLM_FORMAT" in str(exc), exc
    else:
        raise AssertionError("a non-Anthropic LLM_FORMAT should raise")


def test_api_error_raises_instead_of_returning_text():
    async def fake_query(**_):
        yield saf.ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                                is_error=True, num_turns=1, session_id="s",
                                result="API Error: 400 bad model")
    real, saf.query = saf.query, fake_query
    try:
        saf.create_agent_from_markdown(MD).ask("hi")
    except RuntimeError as exc:
        assert "API Error: 400" in str(exc), exc
    else:
        raise AssertionError("an is_error result should raise")
    finally:
        saf.query = real


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

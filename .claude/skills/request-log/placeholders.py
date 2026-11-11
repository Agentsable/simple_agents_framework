"""The one rule for "this part of a report is still unfilled".

A template field is a closed pair of double braces around a short label on one line, with no braces
inside: the fields in report_template.html, such as the task, sha or verdict fields. Two opening
braces quoted in prose (for example in an error report about them) are NOT a field. Used by
build_artifact.py and the evidence-gate.sh hook; the evidence-reviewer applies the same rule.
"""
import re

FIELD = re.compile(r"\{\{[^{}\n]{1,300}\}\}")


def find_placeholders(text: str) -> list[str]:
    """Every unfilled template field in text, in order."""
    return FIELD.findall(text)


def has_placeholder(text: str) -> bool:
    return FIELD.search(text) is not None

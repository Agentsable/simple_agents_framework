#!/usr/bin/env python3
"""Mark the start of a plan step on the current request's timeline (request-log step 4):

    python3 .claude/skills/request-log/log_step.py "S2 parallel: T1 template, T2 metrics"

The report's Timeline section draws one bar per step, from this mark to the next mark or review."""
import sys
from timeline import append, current_folder

if len(sys.argv) < 2 or not sys.argv[1].strip():
    sys.exit('usage: log_step.py "<step label>"')
folder = current_folder()
if not folder:
    sys.exit("No request found: save request.md first.")
e = append(folder, "step", label=" ".join(sys.argv[1:]).strip()[:80])
print(f"{folder.name}: step at {e['t'][11:19]}: {e['label']}")

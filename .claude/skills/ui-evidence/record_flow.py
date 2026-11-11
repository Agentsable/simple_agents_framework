#!/usr/bin/env python3
"""Record a user flow with Playwright, convert it to a GIF, and delete the video.

    record_flow.py <flow.py> --name <flow-name> [--slug S] [--base URL] [--headed]

<flow.py> defines `run(page, base_url, check)` and drives the app with the Playwright sync API (click,
type, wait for the reaction). `check(name, ok, detail)` (also check.equal / check.changed, see
evidence_common.Checks) records a named check of a value the action must change. Outputs, in
requests_and_response/<slug>/ (next to report.html):

    <name>.gif         the recording (5 fps, 800 px wide) - the evidence shown in the report
    <name>-frames.jpg  frames taken from the GIF where the screen changed, side by side - review
                       THIS image: an image viewer shows only a GIF's first frame
    <name>-checks.json the named checks and their PASS/FAIL. The run exits 1 when a check failed,
                       the flow raised, or the flow made no checks (evidence-gate.sh blocks on that).

The .webm Playwright records is removed after conversion: verification uses the GIF only.
"""
import argparse
import importlib.util
import inspect
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageSequence
from playwright.sync_api import sync_playwright

from evidence_common import DEFAULT_BASE, Checks, current_slug, media_dir, require_server

HERE = Path(__file__).resolve().parent
try:  # same viewport as the before/after captures
    VIEWPORT = json.loads((HERE / "pages.json").read_text())["viewport"]
except (OSError, ValueError, KeyError):
    VIEWPORT = {"width": 1440, "height": 900}


def load_flow(path: Path):
    spec = importlib.util.spec_from_file_location("flow", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "run"):
        sys.exit(f"{path} must define run(page, base_url, check)")
    return module.run


def to_gif(video: Path, gif: Path) -> None:
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is required (brew install ffmpeg)")
    vf = ("fps=5,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];"
          "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", vf, str(gif)], check=True)


def content_box(frame):
    """Crop the empty band a recording can have below the page (near-flat rows; GIF dithering
    makes them not quite uniform)."""
    grey = frame.convert("L")
    bottom = grey.height
    while bottom > grey.height // 4:
        low, high = grey.crop((0, bottom - 1, grey.width, bottom)).getextrema()
        if high - low > 24:
            break
        bottom -= 1
    return (0, 0, grey.width, bottom)


def frame_sheet(gif: Path, dest: Path, limit: int = 8, columns: int = 2) -> int:
    """Frames where the picture changed (first, changes, last), in a numbered grid, in time order."""
    frames = [f.convert("RGB") for f in ImageSequence.Iterator(Image.open(gif))]
    scores = [0.0] + [
        sum(ImageChops.difference(a, b).convert("L").histogram()[20:]) / (a.width * a.height)
        for a, b in zip(frames, frames[1:])
    ]
    moments = sorted(range(1, len(frames)), key=lambda i: scores[i], reverse=True)[: limit - 2]
    picks = sorted({0, len(frames) - 1, *[i for i in moments if scores[i] > 0.001]})
    picks = sorted({min(i + 2, len(frames) - 1) for i in picks})[:limit]  # once the change settled
    box = content_box(frames[-1])
    tiles = [frames[i].crop(box) for i in picks]
    gap = 10
    w, h = tiles[0].size
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * w + (columns - 1) * gap, rows * h + (rows - 1) * gap), "#777")
    draw = ImageDraw.Draw(sheet)
    for n, tile in enumerate(tiles):
        x, y = (n % columns) * (w + gap), (n // columns) * (h + gap)
        sheet.paste(tile, (x, y))
        draw.rectangle((x, y, x + 64, y + 26), fill="#222")
        draw.text((x + 8, y + 6), f"{n + 1} · {picks[n] / 5:.1f}s", fill="white")
    sheet.save(dest, quality=82)
    return len(tiles)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("flow", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--slug")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    run = load_flow(args.flow.resolve())
    slug = args.slug or current_slug()
    media = media_dir(slug)
    require_server(args.base)

    with tempfile.TemporaryDirectory() as tmp:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=not args.headed)
            context = browser.new_context(viewport=VIEWPORT, record_video_dir=tmp, record_video_size=VIEWPORT)
            page = context.new_page()
            checks = Checks()
            try:
                if len(inspect.signature(run).parameters) >= 3:
                    run(page, args.base, checks)
                else:  # old two-argument flow: it runs, but it has no checks
                    run(page, args.base)
                page.wait_for_timeout(1000)
            except Exception as error:  # noqa: BLE001 - recorded as a failed check, the GIF is still made
                checks("flow ran to the end", False, f"{type(error).__name__}: {error}".splitlines()[0][:300])
            finally:
                context.close()  # finishes writing the video
                browser.close()
        video = next(Path(tmp).glob("*.webm"))
        gif = media / f"{args.name}.gif"
        to_gif(video, gif)
        # the temporary folder (and the .webm in it) is deleted here

    sheet = media / f"{args.name}-frames.jpg"
    count = frame_sheet(gif, sheet)
    print(f"gif:    {gif} ({gif.stat().st_size // 1024} KB)")
    print(f"frames: {sheet} ({count} frames from the GIF - review this image)")
    if not checks.items:
        checks("flow made at least one check", False, "add check(...) calls for the values the action must change")
    out = media / f"{args.name}-checks.json"
    out.write_text(json.dumps({"flow": args.name, "checks": checks.items}, indent=2))
    print(f"checks: {out} ({len(checks.items) - len(checks.failed)} of {len(checks.items)} passed)")
    if checks.failed:
        sys.exit(f"{len(checks.failed)} check(s) failed: " + "; ".join(c["name"] for c in checks.failed))


if __name__ == "__main__":
    main()

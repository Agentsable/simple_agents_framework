#!/usr/bin/env python3
"""Before/after screenshots of every app view (pages.json) for the current request.

    capture_pages.py before   # BEFORE editing anything that can affect the UI
    capture_pages.py after    # when the change is done: diff against before, build side-by-side images

Options: --slug <request slug> (default: the latest request), --base <app url> (default
app.base_url in .claude/project.json), --only <view,view> (limit to some views).
Each view waits for its `ready` condition (pages.json); exits 1 if a view never got ready or a click failed.

before -> requests_and_response/<slug>/before/<view>.png
after  -> .../after/<view>.png, plus for every view whose pixels changed:
          .../ui-<view>.jpg   Before | After side by side (shown in the report and the artifact)
          .../ui-changes.json {view: changed fraction} for every view, and the list of changed views
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from playwright.sync_api import sync_playwright

from evidence_common import DEFAULT_BASE, current_slug, media_dir, require_server, wait_ready

HERE = Path(__file__).resolve().parent
CHANGED_AT = 0.0005  # fraction of pixels that must differ for a view to count as changed
STILL_CSS = "*, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; }"


def settled_screenshot(page, path: Path, tries: int = 6) -> None:
    """Screenshot once the page stops changing (two identical shots in a row)."""
    previous = None
    for _ in range(tries):
        shot = page.screenshot(animations="disabled")
        if shot == previous:
            break
        previous = shot
        page.wait_for_timeout(300)
    path.write_bytes(shot)


def shoot(views, viewport, base, out: Path, ready=None) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    problems = []
    with sync_playwright() as p:
        # flags that make text rendering repeatable between runs
        browser = p.chromium.launch(channel="chrome", args=[
            "--disable-gpu", "--disable-lcd-text", "--force-color-profile=srgb",
            "--disable-partial-raster", "--font-render-hinting=none"])
        for view in views:
            page = browser.new_page(viewport=viewport)
            page.add_init_script("try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}")
            page.goto(base + view["url"], wait_until="load")
            try:  # the app's own ready signal (pages.json "ready"), not network idle
                wait_ready(page, view.get("ready", ready))
            except Exception:  # noqa: BLE001
                problems.append(f"{view['name']}: not ready ({view.get('ready', ready)!r}) within 15 s")
            page.add_style_tag(content=STILL_CSS)
            page.evaluate("document.fonts.ready")
            for name in view.get("clicks", []):
                target = page.get_by_role("button", name=name, exact=True).first
                if not target.count():
                    target = page.get_by_role("tab", name=name, exact=True).first
                try:
                    target.click(timeout=4000)
                except Exception:  # noqa: BLE001
                    problems.append(f"{view['name']}: no button named {name!r}")
                    break
                page.wait_for_timeout(250)
            page.mouse.move(0, 0)  # no hover state
            settled_screenshot(page, out / f"{view['name']}.png")
            page.close()
        browser.close()
    return problems


def side_by_side(before: Path, after: Path, dest: Path, title: str) -> None:
    a, b = Image.open(before).convert("RGB"), Image.open(after).convert("RGB")
    gap, bar = 16, 44
    canvas = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height) + bar), "white")
    canvas.paste(a, (0, bar))
    canvas.paste(b, (a.width + gap, bar))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    except OSError:
        font = ImageFont.load_default()
    draw.text((8, 10), f"BEFORE · {title}", fill="#7a2e2e", font=font)
    draw.text((a.width + gap + 8, 10), f"AFTER · {title}", fill="#1f6b3a", font=font)
    canvas.thumbnail((2400, 2400))
    canvas.save(dest, quality=82)


def diff_fraction(before: Path, after: Path) -> float:
    a, b = Image.open(before).convert("RGB"), Image.open(after).convert("RGB")
    if a.size != b.size:
        return 1.0
    # soften both so anti-aliasing noise drops out; real changes (text, layout, colour) stay
    soft = lambda im: im.convert("L").filter(ImageFilter.GaussianBlur(1.2))
    hist = ImageChops.difference(soft(a), soft(b)).histogram()
    return sum(hist[40:]) / (a.width * a.height)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["before", "after"])
    parser.add_argument("--slug")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--only")
    args = parser.parse_args()

    config = json.loads((HERE / "pages.json").read_text())
    views = config["views"]
    if args.only:
        wanted = set(args.only.split(","))
        views = [v for v in views if v["name"] in wanted]
    slug = args.slug or current_slug()
    media = media_dir(slug)
    require_server(args.base)

    problems = shoot(views, config["viewport"], args.base, media / args.phase, config.get("ready"))
    for line in problems:
        print("WARN", line)
    if args.phase == "before":
        print(f"before: {len(views)} views -> {media / 'before'}")
        sys.exit(1 if problems else 0)  # a view that never got ready is not valid evidence

    report, changed = {}, []
    for view in views:
        name = view["name"]
        before, after = media / "before" / f"{name}.png", media / "after" / f"{name}.png"
        if not before.exists():
            print(f"WARN {name}: no before image (take before shots before editing)")
            continue
        fraction = diff_fraction(before, after)
        report[name] = round(fraction, 5)
        old = media / f"ui-{name}.jpg"
        if fraction >= CHANGED_AT:
            changed.append(name)
            side_by_side(before, after, old, name)
        elif old.exists():
            old.unlink()
    (media / "ui-changes.json").write_text(json.dumps({"changed": changed, "diff": report}, indent=2))
    print(f"after: {len(changed)} of {len(report)} views changed: {', '.join(changed) or 'none'}")
    for name in changed:
        print(f"  {media / f'ui-{name}.jpg'}  ({report[name]:.2%} of pixels)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()

"""Record the film narration with a Microsoft neural voice and wire it into index.html.

Reads every narrated line straight from index.html (the `v` text if present, else `t`),
writes audio/<scene>-<beat>.mp3 and stores the line durations in the NARR block,
so the player waits for each recording and can estimate the running time.

    pip install edge-tts
    python tools/make_voice.py
"""
import asyncio
import json
import pathlib
import re

import edge_tts

VOICE = "ru-RU-SvetlanaNeural"
RATE = "+5%"
LABEL = "нейроголос «Светлана» (Microsoft)"
BYTES_PER_SEC = 6000  # edge-tts default: 48 kbit/s CBR mono mp3

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"
OUT = ROOT / "audio"


def narr_text(s: str) -> str:
    """Mirror of narrText() in index.html."""
    s = s.replace("*", "")
    s = re.sub(r"^…\s*", "", s)
    s = re.sub(r"\s=\s", " — это ", s)
    s = s.replace("→", " — ").replace("≈", "примерно").replace("·", ",")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:1].upper() + s[1:]


def narration(html: str) -> dict:
    lines = {}
    for scene in re.finditer(r"scene\(\{\s*id: '(\w+)'.*?beats: \[(.*?)\n  \],", html, re.S):
        beats = re.finditer(r"\{ t: '([^']*)'(?:, v: '([^']*)')?", scene.group(2))
        for k, b in enumerate(beats):
            if b.group(1):
                lines[f"{scene.group(1)}-{k}"] = narr_text(b.group(2) or b.group(1))
    return lines


async def record(lines: dict) -> None:
    sem = asyncio.Semaphore(4)

    async def one(key: str, text: str) -> None:
        async with sem:
            for attempt in range(4):
                try:
                    await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(OUT / f"{key}.mp3"))
                    print("ok", key)
                    return
                except Exception as e:  # network hiccups: retry with backoff
                    print("retry", key, e)
                    await asyncio.sleep(2 * (attempt + 1))
            raise SystemExit(f"failed to record {key}")

    await asyncio.gather(*(one(k, t) for k, t in lines.items()))


def main() -> None:
    html = HTML.read_text("utf-8")
    lines = narration(html)
    OUT.mkdir(exist_ok=True)
    for stale in OUT.glob("*.mp3"):
        if stale.stem not in lines:
            stale.unlink()
    asyncio.run(record(lines))
    dur = {k: round((OUT / f"{k}.mp3").stat().st_size / BYTES_PER_SEC, 2) for k in lines}
    block = "/*NARR*/const NARR = " + json.dumps({"voice": LABEL, "dur": dur}, ensure_ascii=False) + ";/*/NARR*/"
    html = re.sub(r"/\*NARR\*/.*?/\*/NARR\*/", lambda _: block, html, flags=re.S)
    HTML.write_text(html, "utf-8", newline="\n")
    print(f"{len(lines)} lines, {sum(dur.values()) / 60:.1f} min of narration")


if __name__ == "__main__":
    main()

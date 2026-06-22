"""Render the Where Wolf? night narration to pre-baked neural-TTS clips.

The narration script is a small FIXED set of lines (``roles.NARRATION``), so we
render each one ONCE, offline, with a good neural voice and ship the mp3s as static
assets. The client (WhereWolf.jsx ``playNarration``) plays them by key and only falls
back to the browser's Web Speech voice when a clip is missing.

Uses ``edge-tts`` — free, no API key, taps Microsoft Edge's online "Natural" neural
voices. Install once:  ``pip install edge-tts``

Run from the repo root:
    python -m games.wherewolf.render_narration

Re-render with a different voice/feel without editing this file:
    python -m games.wherewolf.render_narration --voice en-GB-RyanNeural --rate -10%
    python -m games.wherewolf.render_narration --list        # show candidate voices

Good ominous-announcer voices (all free via edge-tts):
    en-US-ChristopherNeural  (deep male, default)
    en-GB-RyanNeural         (British male)
    en-US-GuyNeural / en-US-DavisNeural
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from games.wherewolf import roles

# Output: webapp/public/<this>  ->  served at  ${BASE_URL}werewolf/narration/<key>.mp3
OUT_DIR = Path(__file__).resolve().parents[2] / "webapp" / "public" / "werewolf" / "narration"

DEFAULT_VOICE = "en-US-ChristopherNeural"   # deep male announcer
DEFAULT_RATE = "-5%"                         # 0.95x = a touch slower than normal
DEFAULT_PITCH = "-4Hz"                       # a touch lower = more ominous

SUGGESTED = [
    "en-US-ChristopherNeural", "en-US-GuyNeural", "en-US-DavisNeural",
    "en-GB-RyanNeural", "en-US-EricNeural", "en-AU-WilliamNeural",
]


async def _render_one(edge_tts, key: str, text: str, voice: str, rate: str, pitch: str) -> None:
    dest = OUT_DIR / f"{key}.mp3"
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await comm.save(str(dest))
    print(f"  {dest.name:16s} <- {text!r}")


async def _render_all(voice: str, rate: str, pitch: str) -> None:
    import edge_tts  # lazy: only needed when actually rendering

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"voice={voice} rate={rate} pitch={pitch}")
    print(f"-> {OUT_DIR}")
    for key, text in roles.NARRATION.items():
        if text:
            await _render_one(edge_tts, key, text, voice, rate, pitch)
    print(f"done: {len(roles.NARRATION)} clips")


async def _list_voices() -> None:
    import edge_tts

    voices = await edge_tts.list_voices()
    for v in sorted(voices, key=lambda x: x["ShortName"]):
        if v["Locale"].startswith("en-") and v.get("Gender") == "Male":
            star = " *" if v["ShortName"] in SUGGESTED else ""
            print(f"  {v['ShortName']:28s} {v['Locale']}{star}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Render Where Wolf? narration to mp3 clips.")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--rate", default=DEFAULT_RATE, help="e.g. -15%% (slower) / +0%%")
    ap.add_argument("--pitch", default=DEFAULT_PITCH, help="e.g. -4Hz (lower) / +0Hz")
    ap.add_argument("--list", action="store_true", help="list English male voices and exit")
    args = ap.parse_args()

    if args.list:
        asyncio.run(_list_voices())
        return
    asyncio.run(_render_all(args.voice, args.rate, args.pitch))


if __name__ == "__main__":
    main()

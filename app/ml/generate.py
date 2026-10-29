"""
Platform-specific generation.

Every output is a list of text "units" (a line of a LinkedIn post, a caption
paragraph, a video scene). The model is asked to end each unit with the
fact ids it used, e.g. "...cut onboarding time by 38%. [F2]". Those markers
are parsed out into `claimed_facts`, then trace.py verifies them
independently.
"""
from __future__ import annotations

import re

from .. import llm

PLATFORMS = ["linkedin", "instagram", "video"]

LIMITS = {
    "linkedin": {"max_chars": 3000, "max_hashtags": 5, "label": "LinkedIn post"},
    "instagram": {"max_chars": 2200, "max_hashtags": 10, "label": "Instagram caption"},
    "video": {"max_seconds": 60, "label": "Short-video script"},
}

SYSTEM = """You repurpose approved source material into social content for a brand.
HARD RULES
1. Use ONLY the facts provided. Never invent numbers, names, features, quotes or results. If a claim is not in the facts, do not make it.
2. Keep every number and name exactly as written in the facts.
3. After each line or scene that uses a fact, append the fact ids in square brackets, e.g. "[F2]" or "[F1, F4]". Lines with no fact (greetings, questions, CTAs) get no bracket.
4. Follow the brand voice. Do not use any banned word. Use the preferred terms where natural.
5. Reply with ONLY the JSON object requested."""

FORMAT = {
    "linkedin": """Write a LinkedIn post. JSON: {"hook": "first line, under 20 words, no clickbait", "lines": ["one short paragraph per item, 4-7 items, each 1-2 sentences"], "cta": "one line", "hashtags": ["3-5 without #"]}""",
    "instagram": """Write an Instagram carousel caption + slides. JSON: {"hook": "first caption line", "slides": ["slide 1 text (max 12 words)", "... 5-7 slides"], "caption": ["2-4 short caption paragraphs"], "cta": "one line", "hashtags": ["5-10 without #"]}""",
    "video": """Write a 45-60 second short-video script (Reels/Shorts/TikTok). JSON: {"title": "working title", "scenes": [{"time": "0-3s", "on_screen": "text overlay, max 8 words", "voiceover": "spoken line, max 25 words", "visual": "what we see"}], "cta": "closing line"} with 6-9 scenes.""",
}

_MARK = re.compile(r"\s*\[\s*((?:F\d+\s*,?\s*)+)\]\s*$")


def _voice_text(voice: dict) -> str:
    return f"""BRAND VOICE
Tone: {voice.get('tone', 'clear, confident, human')}
Point of view: {voice.get('pov', 'we')}
Reading level: {voice.get('reading_level', 'plain, short sentences')}
Preferred terms: {', '.join(voice.get('preferred', [])) or 'none'}
Banned words/phrases: {', '.join(voice.get('banned', [])) or 'none'}
Emoji: {voice.get('emoji', 'none')}
Audience: {voice.get('audience', 'general professional audience')}"""


def _facts_text(facts: list[dict]) -> str:
    return "APPROVED FACTS\n" + "\n".join(f"{f['id']}: {f['fact']}" for f in facts)


def split_marks(text: str) -> tuple[str, list[str]]:
    """'...by 38%. [F2, F4]' -> ('...by 38%.', ['F2','F4'])"""
    m = _MARK.search(text or "")
    if not m:
        return (text or "").strip(), []
    ids = re.findall(r"F\d+", m.group(1))
    return text[: m.start()].strip(), ids


def _units_from(platform: str, data: dict) -> list[dict]:
    """Normalise the model JSON into ordered units {role, text, claimed_facts, meta}."""
    units = []

    def add(role, text, meta=None):
        t, ids = split_marks(str(text))
        if t:
            units.append({"role": role, "text": t, "claimed_facts": ids, "meta": meta or {}})

    if platform == "linkedin":
        add("hook", data.get("hook", ""))
        for ln in data.get("lines") or []:
            add("body", ln)
        add("cta", data.get("cta", ""))
    elif platform == "instagram":
        add("hook", data.get("hook", ""))
        for i, s in enumerate(data.get("slides") or [], 1):
            add("slide", s, {"slide": i})
        for p in data.get("caption") or []:
            add("body", p)
        add("cta", data.get("cta", ""))
    else:
        add("title", data.get("title", ""))
        for i, sc in enumerate(data.get("scenes") or [], 1):
            if not isinstance(sc, dict):
                continue
            add("scene", sc.get("voiceover", ""), {"scene": i, "time": sc.get("time", ""), "on_screen": split_marks(str(sc.get("on_screen", "")))[0], "visual": sc.get("visual", "")})
        add("cta", data.get("cta", ""))
    return units


def _hashtags(data: dict, platform: str) -> list[str]:
    tags = data.get("hashtags") or []
    lim = LIMITS[platform].get("max_hashtags", 0)
    return [re.sub(r"[^A-Za-z0-9_]", "", str(t)) for t in tags if str(t).strip()][:lim]


# ---------------------------------------------------------------- offline

def _offline(platform: str, facts: list[dict], voice: dict, title: str) -> dict:
    top = facts[:6]
    pov = "We" if voice.get("pov", "we") == "we" else "I"
    if platform == "linkedin":
        data = {
            "hook": f"{title or 'A quick read'}: the numbers that matter. " if title else "Here is what changed, in plain terms.",
            "lines": [f"{f['fact']} [{f['id']}]" for f in top[:5]],
            "cta": f"{pov}'d like to hear how this compares to your experience.",
            "hashtags": [re.sub(r"[^A-Za-z0-9]", "", w) for w in (voice.get("preferred") or ["Update", "Results"])[:4]],
        }
    elif platform == "instagram":
        data = {
            "hook": "Swipe for the short version.",
            "slides": [f"{' '.join(f['fact'].split()[:12])} [{f['id']}]" for f in top[:6]],
            "caption": [f"{f['fact']} [{f['id']}]" for f in top[:3]],
            "cta": "Save this and share it with someone who should know.",
            "hashtags": [re.sub(r"[^A-Za-z0-9]", "", w) for w in (voice.get("preferred") or ["Update", "Results", "HowItWorks"])[:6]],
        }
    else:
        scenes, t = [], 0
        for i, f in enumerate(top[:7], 1):
            dur = 8 if i > 1 else 3
            scenes.append({"time": f"{t}-{t+dur}s", "on_screen": " ".join(f["fact"].split()[:6]), "voiceover": f"{f['fact']} [{f['id']}]", "visual": "B-roll or talking head"})
            t += dur
        data = {"title": title or "What you need to know", "scenes": scenes, "cta": "Follow for the next update."}
    return data


# ---------------------------------------------------------------- public

def generate(platform: str, facts: list[dict], voice: dict, title: str = "", extra: str = "") -> tuple[dict, str]:
    """Return ({units, hashtags, raw}, mode)."""
    assert platform in PLATFORMS
    mode = "llm"
    data = None
    if llm.available() and facts:
        prompt = f"SOURCE TITLE: {title}\n\n{_facts_text(facts)}\n\n{_voice_text(voice)}\n\n{FORMAT[platform]}"
        if extra:
            prompt += f"\n\nADDITIONAL INSTRUCTIONS: {extra}"
        try:
            data = llm.complete_json(SYSTEM, prompt, max_tokens=2500, temperature=0.7)
            if not isinstance(data, dict):
                data = None
        except Exception:
            data = None
    if data is None:
        data = _offline(platform, facts, voice, title)
        mode = "offline"
    return {"units": _units_from(platform, data), "hashtags": _hashtags(data, platform), "raw": data}, mode


def revise(platform: str, facts: list[dict], voice: dict, units: list[dict], problems: list[str], title: str = "") -> tuple[dict, str] | None:
    """Ask the model to fix listed problems while keeping fact citations. None in offline mode."""
    if not llm.available():
        return None
    current = "\n".join(f"- ({u['role']}) {u['text']}" + (f" [{', '.join(u['claimed_facts'])}]" if u['claimed_facts'] else "") for u in units)
    prompt = (f"SOURCE TITLE: {title}\n\n{_facts_text(facts)}\n\n{_voice_text(voice)}\n\n"
              f"CURRENT DRAFT:\n{current}\n\nPROBLEMS FOUND BY THE REVIEWER:\n- " + "\n- ".join(problems) +
              f"\n\nRewrite the draft fixing every problem. Keep what already works.\n{FORMAT[platform]}")
    try:
        data = llm.complete_json(SYSTEM, prompt, max_tokens=2500, temperature=0.5)
        if isinstance(data, dict):
            return {"units": _units_from(platform, data), "hashtags": _hashtags(data, platform), "raw": data}, "llm"
    except Exception:
        pass
    return None

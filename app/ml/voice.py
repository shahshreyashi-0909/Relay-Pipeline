"""
Brand-voice enforcement.

Checks every draft against the brand profile:
  * banned words / phrases (hard fail, with the offending unit)
  * preferred terms coverage
  * tone classifier: TF-IDF + logistic regression trained on labelled
    snippets (formal / conversational / salesy / technical). The draft's
    predicted tone is compared with the brand's target tone.
  * readability: Flesch reading ease, avg sentence length
  * platform limits: character count, hashtag count, video length
  * emoji policy

Returns a score and a list of problems the generator can be asked to fix.
"""
from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from .generate import LIMITS

TONES = ["formal", "conversational", "salesy", "technical"]

_SEED = [
    ("We are pleased to announce the completion of the quarterly review.", "formal"),
    ("The organisation remains committed to delivering measurable outcomes for stakeholders.", "formal"),
    ("Please find the updated policy attached for your reference.", "formal"),
    ("Our findings indicate a consistent improvement across all regions.", "formal"),
    ("This report summarises the methodology and the resulting recommendations.", "formal"),
    ("Kindly note that the deadline has been extended to Friday.", "formal"),
    ("Okay, real talk: this took us way longer than we thought.", "conversational"),
    ("Here's the thing nobody tells you about onboarding.", "conversational"),
    ("We tried it for a month. Here's what happened.", "conversational"),
    ("Quick one for anyone who's ever lost a file at 2am.", "conversational"),
    ("Honestly? The simple version worked better.", "conversational"),
    ("You know that feeling when the dashboard finally loads? That.", "conversational"),
    ("Don't miss out! Limited time offer, grab yours today!", "salesy"),
    ("Unlock explosive growth with our revolutionary all-in-one platform!", "salesy"),
    ("Sign up now and get 50% off, this week only!", "salesy"),
    ("The #1 tool trusted by thousands, try it free, no credit card needed!", "salesy"),
    ("Transform your business overnight with game-changing results!", "salesy"),
    ("Hurry, only a few spots left, book now!", "salesy"),
    ("The service exposes a REST endpoint that returns paginated JSON.", "technical"),
    ("Latency dropped from 420 ms to 180 ms after enabling connection pooling.", "technical"),
    ("We migrated the queue to a partitioned topic with idempotent consumers.", "technical"),
    ("The model uses TF-IDF features with an L2-regularised linear classifier.", "technical"),
    ("Configure the retry policy via the exponential backoff parameter.", "technical"),
    ("Throughput scales linearly up to 32 workers before contention appears.", "technical"),
]
_TONE_MODEL = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True), LogisticRegression(max_iter=1000, C=3.0))
_TONE_MODEL.fit([t for t, _ in _SEED], [l for _, l in _SEED])

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_VOWELS = re.compile(r"[aeiouy]+")


def _syllables(word: str) -> int:
    w = word.lower().strip(".,;:!?\"'()")
    if not w:
        return 0
    n = len(_VOWELS.findall(w))
    if w.endswith("e") and n > 1:
        n -= 1
    return max(1, n)


def readability(text: str) -> dict:
    sents = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = [w for w in re.findall(r"[A-Za-z']+", text)]
    if not sents or not words:
        return {"flesch": 0, "avg_sentence_len": 0, "grade": 0}
    syl = sum(_syllables(w) for w in words)
    asl = len(words) / len(sents)
    asw = syl / len(words)
    flesch = 206.835 - 1.015 * asl - 84.6 * asw
    grade = 0.39 * asl + 11.8 * asw - 15.59
    return {"flesch": round(flesch, 1), "avg_sentence_len": round(asl, 1), "grade": round(max(0, grade), 1)}


def tone_profile(text: str) -> dict:
    probs = _TONE_MODEL.predict_proba([text])[0]
    return {c: round(float(p), 2) for c, p in zip(_TONE_MODEL.classes_, probs)}


def _target_tone(voice: dict) -> str:
    t = (voice.get("tone") or "").lower()
    if any(k in t for k in ("formal", "professional", "authoritative", "corporate")):
        return "formal"
    if any(k in t for k in ("technical", "precise", "engineer", "developer")):
        return "technical"
    return "conversational"


def check(platform: str, draft: dict, voice: dict) -> dict:
    units = draft["units"]
    full = "\n".join(u["text"] for u in units)
    problems, warnings = [], []

    # banned words (whole-word / phrase, case-insensitive)
    banned_hits = []
    for b in voice.get("banned") or []:
        pat = re.compile(r"\b" + re.escape(b.strip()) + r"\b", re.I)
        for u in units:
            if pat.search(u["text"]):
                banned_hits.append({"term": b, "text": u["text"]})
                u.setdefault("voice_issues", []).append(f"banned: {b}")
    for h in banned_hits:
        problems.append(f"Banned word “{h['term']}” in: “{h['text'][:60]}…”")

    # preferred terms
    preferred = voice.get("preferred") or []
    used_pref = [p for p in preferred if re.search(r"\b" + re.escape(p) + r"\b", full, re.I)]
    if preferred and len(used_pref) == 0:
        warnings.append(f"None of the preferred terms were used ({', '.join(preferred[:4])}).")

    # tone
    target = _target_tone(voice)
    tp = tone_profile(full)
    predicted = max(tp, key=tp.get)
    if tp.get("salesy", 0) >= 0.45 and target != "salesy":
        problems.append(f"Draft reads as salesy ({tp['salesy']:.0%}); the brand tone is {voice.get('tone') or target}. Remove hype and urgency language.")
    elif predicted != target and tp[predicted] - tp.get(target, 0) > 0.25:
        warnings.append(f"Draft leans {predicted} ({tp[predicted]:.0%}) rather than {target}.")

    # readability
    rd = readability(full)
    level = (voice.get("reading_level") or "").lower()
    if ("plain" in level or "simple" in level or "short" in level) and rd["avg_sentence_len"] > 22:
        problems.append(f"Average sentence is {rd['avg_sentence_len']} words; the brand asks for short, plain sentences.")

    # emoji policy
    emoji_count = len(_EMOJI.findall(full))
    if (voice.get("emoji") or "none").lower().startswith("none") and emoji_count:
        problems.append(f"{emoji_count} emoji used but the brand policy is no emoji.")

    # platform limits
    lim = LIMITS[platform]
    chars = len(full)
    if "max_chars" in lim and chars > lim["max_chars"]:
        problems.append(f"{chars} characters, over the {lim['label']} limit of {lim['max_chars']}.")
    tags = draft.get("hashtags") or []
    if "max_hashtags" in lim and len(tags) > lim["max_hashtags"]:
        warnings.append(f"{len(tags)} hashtags; keep it under {lim['max_hashtags']}.")
    if platform == "video":
        secs = 0
        for u in units:
            m = re.search(r"(\d+)\s*-\s*(\d+)\s*s", str(u.get("meta", {}).get("time", "")))
            if m:
                secs = max(secs, int(m.group(2)))
        if secs > lim["max_seconds"]:
            problems.append(f"Script runs to {secs}s; keep it under {lim['max_seconds']}s.")
        spoken = sum(len(u["text"].split()) for u in units if u["role"] == "scene")
        if spoken > 170:
            warnings.append(f"{spoken} spoken words, which is over ~160 for a 60s read.")

    score = max(0, 100 - 18 * len(problems) - 5 * len(warnings))
    return {
        "score": score, "problems": problems, "warnings": warnings,
        "banned_hits": banned_hits, "preferred_used": used_pref,
        "tone": tp, "target_tone": target, "readability": rd,
        "chars": chars, "hashtag_count": len(tags), "emoji_count": emoji_count,
    }

"""
Source ingestion: pasted text or a URL → clean text → numbered sentences
with character offsets, plus the "hard facts" (numbers, money, percentages,
dates, proper nouns) found in each sentence. Those offsets are what every
generated post points back to.
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; RelayPipeline/1.0)"

_ABBREV = {"e.g", "i.e", "vs", "mr", "mrs", "ms", "dr", "inc", "ltd", "co", "no", "etc", "approx", "fig", "st", "jr", "sr"}
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"'(])")

NUMBER_RE = re.compile(r"(?<![\w.])(?:[$€£₹]\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m|bn|million|billion|crore|lakh)?|\d[\d,]*(?:\.\d+)?\s?(?:%|percent|x|k|m|bn|million|billion|crore|lakh|hours?|days?|weeks?|months?|years?|minutes?|seconds?)?)(?![\w])", re.I)
PROPER_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9&'’-]+(?:\s+[A-Z][a-zA-Z0-9&'’-]+){0,3})\b")
STOP_PROPER = {"The", "A", "An", "In", "On", "At", "We", "Our", "It", "This", "That", "These", "Those", "For", "With", "And", "But", "By", "From", "To", "Of", "As", "If", "When", "While", "After", "Before", "I", "You", "They", "He", "She", "Here", "There", "What", "How", "Why", "Who", "Yes", "No"}


def fetch_url(url: str) -> tuple[str, str]:
    """Return (title, main text) for a web page."""
    r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    for t in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"]):
        t.decompose()
    title = (soup.title.string if soup.title and soup.title.string else "").strip()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    paras = []
    for el in main.find_all(["h1", "h2", "h3", "p", "li", "blockquote"]):
        txt = " ".join(el.get_text(" ", strip=True).split())
        if len(txt) > 30 or el.name.startswith("h"):
            paras.append(txt)
    text = "\n\n".join(paras)
    return title, text


def clean(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(text: str) -> list[dict]:
    """Sentence records: {id, text, start, end, paragraph}. Offsets index into `text`."""
    out = []
    pos = 0
    sid = 0
    for pi, para in enumerate(text.split("\n\n")):
        para_start = text.index(para, pos)
        pos = para_start + len(para)
        # protect abbreviations from splitting
        protected = para
        for ab in _ABBREV:
            protected = re.sub(rf"\b({ab})\.", lambda m: m.group(1) + "․", protected, flags=re.I)
        cursor = 0
        for piece in _SENT_END.split(protected):
            piece_clean = piece.replace("․", ".")
            s = para.find(piece_clean, cursor)
            if s < 0:
                continue
            e = s + len(piece_clean)
            cursor = e
            t = piece_clean.strip()
            if len(t) < 3:
                continue
            out.append({"id": f"S{sid}", "text": t, "start": para_start + s, "end": para_start + e, "paragraph": pi})
            sid += 1
    return out


def hard_facts(sentence: str) -> dict:
    """Numbers / money / percentages and proper nouns in a sentence."""
    nums = [m.group(0).strip() for m in NUMBER_RE.finditer(sentence)]
    nums = [n for n in nums if re.search(r"\d", n)]
    props = [m.group(0) for m in PROPER_RE.finditer(sentence)]
    props = [p for p in props if p.split()[0] not in STOP_PROPER and len(p) > 2]
    return {"numbers": nums, "entities": props}


def normalise_number(n: str) -> str:
    return re.sub(r"[\s,]", "", n.lower()).replace("percent", "%")


def ingest(text: str | None = None, url: str | None = None) -> dict:
    title = ""
    if url and not text:
        title, text = fetch_url(url)
    text = clean(text or "")
    sentences = split_sentences(text)
    for s in sentences:
        s.update(hard_facts(s["text"]))
    all_numbers = sorted({normalise_number(n) for s in sentences for n in s["numbers"]})
    all_entities = sorted({e for s in sentences for e in s["entities"]})
    return {
        "title": title, "text": text, "sentences": sentences,
        "numbers": all_numbers, "entities": all_entities,
        "word_count": len(text.split()),
    }

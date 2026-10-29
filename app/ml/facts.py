"""
Fact extraction: the source is reduced to a numbered list of atomic,
verifiable claims, each tied to the sentence(s) it came from.

LLM mode: Claude lists the facts and cites sentence ids. Each cited id is
verified against the source text (a fact that cites nothing real is
dropped). Offline mode: sentences that carry a number, an entity, or a
strong verb become facts directly.
"""
from __future__ import annotations

import re

from .. import llm

SYSTEM = """You extract atomic facts from a source document for a content team.
A fact is one checkable claim: a number, a feature, a result, a date, a quote, a definition.
Rules: keep the source's wording for numbers and names exactly; never add, round or infer;
each fact cites the sentence ids it comes from. Reply with ONLY a JSON array of
{"id": "F1", "fact": "...", "sentence_ids": ["S3"], "kind": "number|feature|result|quote|date|definition|other"}.
Extract between 6 and 20 facts, most important first."""

_STRONG = re.compile(r"\b(launch|reduc|increas|grow|cut|sav|improv|deliver|support|integrat|offer|includ|allow|enabl|help|found|report|announc|won|achiev|built|serv)\w*", re.I)


def _offline(doc: dict) -> list[dict]:
    facts = []
    for s in doc["sentences"]:
        score = 2 * len(s["numbers"]) + len(s["entities"]) + (1 if _STRONG.search(s["text"]) else 0)
        if score >= 2 and 40 <= len(s["text"]) <= 320:
            kind = "number" if s["numbers"] else "feature"
            facts.append({"fact": s["text"], "sentence_ids": [s["id"]], "kind": kind, "score": score})
    facts.sort(key=lambda f: -f["score"])
    out = []
    for i, f in enumerate(facts[:16], 1):
        f.pop("score")
        f["id"] = f"F{i}"
        out.append(f)
    return out


def extract(doc: dict) -> tuple[list[dict], str]:
    if not llm.available() or not doc["sentences"]:
        return _offline(doc), "offline"
    numbered = "\n".join(f"[{s['id']}] {s['text']}" for s in doc["sentences"])[:60000]
    try:
        data = llm.complete_json(SYSTEM, f"SOURCE TITLE: {doc.get('title','')}\n\nSOURCE SENTENCES:\n{numbered}", max_tokens=3000, temperature=0.2)
    except Exception:
        return _offline(doc), "offline"
    valid_ids = {s["id"] for s in doc["sentences"]}
    out = []
    for i, f in enumerate(data if isinstance(data, list) else [], 1):
        if not isinstance(f, dict) or not f.get("fact"):
            continue
        sids = [x for x in (f.get("sentence_ids") or []) if x in valid_ids]
        if not sids:
            continue
        out.append({"id": f"F{i}", "fact": str(f["fact"]).strip()[:400], "sentence_ids": sids,
                    "kind": str(f.get("kind", "other"))})
    return (out, "llm") if out else (_offline(doc), "offline")

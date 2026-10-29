"""
Source-to-post traceability.

For every output unit:
  * claimed facts  — the ids the generator cited
  * matched facts  — facts whose embedding is close to the unit (cosine), so a
                     citation is confirmed independently of the model
  * number check   — every number in the unit must appear in the source
  * verdict        — supported | partial | unsupported | neutral

Numbers that are not in the source are the single most dangerous error in
repurposing, so they are a hard failure regardless of similarity.
"""
from __future__ import annotations

import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy.sparse import hstack

from .ingest import NUMBER_RE, normalise_number

SUPPORT_THRESHOLD = 0.32     # cosine (TF-IDF space) for "supported"
PARTIAL_THRESHOLD = 0.18
NEUTRAL_ROLES = {"cta", "title"}
_NEUTRAL_PATTERNS = re.compile(r"^(what do you think|agree\?|save this|follow|share|comment|tag|swipe|link in bio|drop a|let us know|dm us|thoughts\?)", re.I)


def _embed_all(texts: list[str]) -> np.ndarray:
    word = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
    char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    m = hstack([word.fit_transform(texts), char.fit_transform(texts)]).toarray()
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1
    return m / n


def _numbers(text: str) -> list[str]:
    return [normalise_number(m.group(0)) for m in NUMBER_RE.finditer(text) if re.search(r"\d", m.group(0))]


def _num_in_source(n: str, source_numbers: set[str]) -> bool:
    if n in source_numbers:
        return True
    core = re.sub(r"[^\d.]", "", n)  # "38%" vs "38 percent" vs "38"
    return any(re.sub(r"[^\d.]", "", s) == core for s in source_numbers) if core else True


def trace(units: list[dict], facts: list[dict], doc: dict) -> dict:
    """Annotate units in place and return a summary."""
    if not units:
        return {"supported": 0, "partial": 0, "unsupported": 0, "neutral": 0, "coverage": 0, "score": 100, "problems": []}
    fact_texts = [f["fact"] for f in facts] or [""]
    sent_texts = [s["text"] for s in doc["sentences"]] or [""]
    unit_texts = [u["text"] for u in units]
    vecs = _embed_all(unit_texts + fact_texts + sent_texts)
    U = vecs[: len(units)]
    F = vecs[len(units): len(units) + len(fact_texts)]
    S = vecs[len(units) + len(fact_texts):]
    sim_f = U @ F.T
    sim_s = U @ S.T
    source_numbers = set(doc.get("numbers", []))
    fact_by_id = {f["id"]: f for f in facts}
    problems: list[str] = []
    counts = {"supported": 0, "partial": 0, "unsupported": 0, "neutral": 0}
    used_facts: set[str] = set()

    for i, u in enumerate(units):
        best_f = int(np.argmax(sim_f[i])) if facts else -1
        best_s = int(np.argmax(sim_s[i])) if doc["sentences"] else -1
        f_score = float(sim_f[i, best_f]) if facts else 0.0
        s_score = float(sim_s[i, best_s]) if doc["sentences"] else 0.0
        matched = [facts[j]["id"] for j in np.argsort(-sim_f[i])[:3] if sim_f[i, j] >= PARTIAL_THRESHOLD] if facts else []
        # verify claimed citations: a claimed fact counts if it is in the matched set or is itself similar enough
        verified_claims = [c for c in u["claimed_facts"] if c in fact_by_id and (c in matched or sim_f[i, facts.index(fact_by_id[c])] >= PARTIAL_THRESHOLD)]
        bad_claims = [c for c in u["claimed_facts"] if c in fact_by_id and c not in verified_claims]
        unknown_claims = [c for c in u["claimed_facts"] if c not in fact_by_id]
        nums = _numbers(u["text"])
        bad_nums = [n for n in nums if not _num_in_source(n, source_numbers)]

        is_neutral = u["role"] in NEUTRAL_ROLES or (not u["claimed_facts"] and not nums and (u["role"] == "hook" or bool(_NEUTRAL_PATTERNS.match(u["text"])) or len(u["text"].split()) <= 6))
        if bad_nums:
            verdict = "unsupported"
            problems.append(f"“{u['text'][:70]}…” uses {', '.join(bad_nums)} which does not appear in the source.")
        elif is_neutral:
            verdict = "neutral"
        elif max(f_score, s_score) >= SUPPORT_THRESHOLD or verified_claims:
            verdict = "supported"
        elif max(f_score, s_score) >= PARTIAL_THRESHOLD:
            verdict = "partial"
            problems.append(f"“{u['text'][:70]}…” only loosely matches the source (similarity {max(f_score, s_score):.2f}). Tie it to a specific fact or cut it.")
        else:
            verdict = "unsupported"
            problems.append(f"“{u['text'][:70]}…” is not supported by any approved fact.")
        if bad_claims:
            problems.append(f"“{u['text'][:50]}…” cites {', '.join(bad_claims)} but does not resemble that fact.")

        src_sent = doc["sentences"][best_s]["id"] if best_s >= 0 else None
        cited_sents = sorted({sid for c in verified_claims for sid in fact_by_id[c]["sentence_ids"]})
        u.update({
            "verdict": verdict,
            "matched_facts": matched,
            "verified_facts": verified_claims,
            "bad_claims": bad_claims + unknown_claims,
            "numbers": nums, "bad_numbers": bad_nums,
            "fact_similarity": round(f_score, 2), "source_similarity": round(s_score, 2),
            "source_sentences": cited_sents or ([src_sent] if src_sent and verdict != "neutral" else []),
        })
        used_facts.update(verified_claims or (matched[:1] if verdict == "supported" else []))
        counts[verdict] += 1

    n_claims = len(units) - counts["neutral"]
    score = 100 if n_claims == 0 else round(100 * (counts["supported"] + 0.5 * counts["partial"]) / n_claims)
    score -= 10 * sum(len(u.get("bad_numbers", [])) for u in units)
    return {
        **counts,
        "coverage": round(len(used_facts) / len(facts), 2) if facts else 0,
        "used_facts": sorted(used_facts, key=lambda x: int(x[1:])),
        "score": max(0, score), "problems": problems,
    }

"""
The repurposing pipeline: ingest → facts → generate → trace → voice → (revise).

`run()` returns a job dict the UI renders. Each platform draft keeps its
units with per-unit verdicts and source pointers, so the front-end can
highlight the exact source sentence a line came from.
"""
from __future__ import annotations

from .ml import ingest, facts as facts_mod, generate, trace, voice as voice_mod

MAX_REVISIONS = 1


def build_draft(platform: str, fact_list: list[dict], voice: dict, doc: dict, title: str, extra: str = "") -> dict:
    draft, mode = generate.generate(platform, fact_list, voice, title, extra)
    draft["platform"] = platform
    draft["mode"] = mode
    draft["trace"] = trace.trace(draft["units"], fact_list, doc)
    draft["voice"] = voice_mod.check(platform, draft, voice)
    draft["revisions"] = 0
    # one automatic revision pass if the reviewer found hard problems
    problems = draft["trace"]["problems"] + draft["voice"]["problems"]
    if problems and mode == "llm":
        for _ in range(MAX_REVISIONS):
            fixed = generate.revise(platform, fact_list, voice, draft["units"], problems, title)
            if not fixed:
                break
            new, _ = fixed
            new.update({"platform": platform, "mode": "llm", "revisions": draft["revisions"] + 1})
            new["trace"] = trace.trace(new["units"], fact_list, doc)
            new["voice"] = voice_mod.check(platform, new, voice)
            if new["trace"]["score"] + new["voice"]["score"] >= draft["trace"]["score"] + draft["voice"]["score"]:
                draft = new
            problems = draft["trace"]["problems"] + draft["voice"]["problems"]
            if not problems:
                break
    draft["score"] = round(0.6 * draft["trace"]["score"] + 0.4 * draft["voice"]["score"])
    return draft


def run(source_text: str | None, source_url: str | None, voice: dict, platforms: list[str], title: str = "") -> dict:
    doc = ingest.ingest(text=source_text, url=source_url)
    title = title or doc.get("title") or ""
    fact_list, fact_mode = facts_mod.extract(doc)
    drafts = {p: build_draft(p, fact_list, voice, doc, title) for p in platforms}
    return {
        "title": title, "source": doc, "facts": fact_list, "fact_mode": fact_mode,
        "voice_profile": voice, "drafts": drafts,
        "overall": round(sum(d["score"] for d in drafts.values()) / len(drafts)) if drafts else 0,
    }

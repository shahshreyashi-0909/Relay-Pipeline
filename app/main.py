"""
Relay — Social Content Repurposing Pipeline
Flask API + static SaaS front-end.

Run:  python -m app.main   (or ./run.sh)
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file, send_from_directory

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import llm, pipeline, store                 # noqa: E402
from .ml import generate, trace, voice as voice_mod  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "static"
app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
app.json.sort_keys = False
store.init()


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/api/status")
def status():
    return jsonify({"llm": llm.available(), "model": llm.DEFAULT_MODEL if llm.available() else None,
                    "platforms": generate.PLATFORMS, "limits": generate.LIMITS})


@app.post("/api/jobs")
def create_job():
    body = request.get_json(force=True) or {}
    text, url = (body.get("text") or "").strip(), (body.get("url") or "").strip()
    if not text and not url:
        return jsonify({"error": "Paste source text or give a URL"}), 400
    platforms = [p for p in (body.get("platforms") or generate.PLATFORMS) if p in generate.PLATFORMS]
    try:
        job = pipeline.run(text or None, url or None, body.get("voice") or {}, platforms, body.get("title") or "")
    except Exception as e:  # URL fetch failures etc.
        return jsonify({"error": f"Could not process source: {e}"}), 400
    job["source_url"] = url
    store.save_job(job)
    return jsonify(job)


@app.get("/api/jobs")
def jobs():
    return jsonify(store.list_jobs())


@app.get("/api/jobs/<jid>")
def get_job(jid):
    j = store.get_job(jid)
    return (jsonify(j), 200) if j else (jsonify({"error": "not found"}), 404)


@app.delete("/api/jobs/<jid>")
def delete_job(jid):
    store.delete_job(jid)
    return jsonify({"ok": True})


@app.post("/api/jobs/<jid>/drafts/<platform>/regenerate")
def regenerate(jid, platform):
    job = store.get_job(jid)
    if not job or platform not in generate.PLATFORMS:
        return jsonify({"error": "not found"}), 404
    extra = (request.get_json(silent=True) or {}).get("instructions", "")
    job["drafts"][platform] = pipeline.build_draft(platform, job["facts"], job["voice_profile"], job["source"], job["title"], extra)
    job["overall"] = round(sum(d["score"] for d in job["drafts"].values()) / len(job["drafts"]))
    store.save_job(job)
    return jsonify(job)


@app.put("/api/jobs/<jid>/drafts/<platform>")
def edit_draft(jid, platform):
    """Manual edit of unit texts → re-run trace + voice checks (no LLM call)."""
    job = store.get_job(jid)
    if not job or platform not in job["drafts"]:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(force=True) or {}
    draft = job["drafts"][platform]
    texts = body.get("texts") or {}
    new_units = []
    for i, u in enumerate(draft["units"]):
        t = texts.get(str(i), u["text"])
        clean, ids = generate.split_marks(t)
        if clean:
            new_units.append({**u, "text": clean, "claimed_facts": ids or u.get("claimed_facts", [])})
    draft["units"] = new_units
    if "hashtags" in body:
        draft["hashtags"] = [str(t).lstrip("#") for t in body["hashtags"]][:10]
    draft["trace"] = trace.trace(draft["units"], job["facts"], job["source"])
    draft["voice"] = voice_mod.check(platform, draft, job["voice_profile"])
    draft["score"] = round(0.6 * draft["trace"]["score"] + 0.4 * draft["voice"]["score"])
    draft["mode"] = "edited"
    job["overall"] = round(sum(d["score"] for d in job["drafts"].values()) / len(job["drafts"]))
    store.save_job(job)
    return jsonify(job)


@app.get("/api/jobs/<jid>/export.<fmt>")
def export(jid, fmt):
    job = store.get_job(jid)
    if not job:
        return jsonify({"error": "not found"}), 404
    if fmt == "json":
        return send_file(io.BytesIO(json.dumps(job, indent=2).encode()), mimetype="application/json",
                         as_attachment=True, download_name=f"relay-{jid}.json")
    if fmt == "md":
        return send_file(io.BytesIO(_markdown(job).encode()), mimetype="text/markdown",
                         as_attachment=True, download_name=f"relay-{jid}.md")
    return jsonify({"error": "unknown format"}), 400


def _markdown(job: dict) -> str:
    out = [f"# {job.get('title') or 'Repurposed content'}", ""]
    for p, d in job["drafts"].items():
        out += [f"## {generate.LIMITS[p]['label']}  (score {d['score']})", ""]
        for u in d["units"]:
            meta = u.get("meta", {})
            prefix = f"**{meta['time']}** " if meta.get("time") else ""
            cites = f"  ⟵ {', '.join(u.get('verified_facts') or u.get('matched_facts') or [])}" if u.get("verdict") not in ("neutral",) else ""
            out.append(f"{prefix}{u['text']}{cites}")
            if meta.get("on_screen"):
                out.append(f"  _On screen: {meta['on_screen']}_")
            out.append("")
        if d.get("hashtags"):
            out.append(" ".join("#" + h for h in d["hashtags"]))
            out.append("")
    out += ["## Fact register", ""]
    for f in job["facts"]:
        out.append(f"- **{f['id']}** {f['fact']}  (source: {', '.join(f['sentence_ids'])})")
    return "\n".join(out)


# voice profiles
@app.get("/api/voices")
def voices():
    return jsonify(store.list_voices())


@app.post("/api/voices")
def save_voice():
    return jsonify(store.save_voice(request.get_json(force=True) or {}))


@app.delete("/api/voices/<vid>")
def delete_voice(vid):
    store.delete_voice(vid)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"Relay running on http://localhost:{port}  (LLM: {'on' if llm.available() else 'offline fallback'})")
    app.run(host="0.0.0.0", port=port, debug=os.getenv("DEBUG") == "1")

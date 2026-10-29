/* Relay front-end. Plain JS over the Flask API. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const LABEL = { linkedin: "LinkedIn", instagram: "Instagram", video: "Short video" };

const state = { job: null, platform: "linkedin", dirty: false, status: null };

const SAMPLE_VOICE = { name: "Northwind house style", tone: "warm, practical, no hype", pov: "we", emoji: "none", reading_level: "plain, short sentences", audience: "retail operations leaders in India", preferred: "Guided Setup, retail teams", banned: "game-changing, revolutionary, unlock, synergy, seamless" };
const SAMPLE_TEXT = `Northwind Analytics cut onboarding time by 38% for mid-size retailers

Northwind Analytics is a reporting platform used by 1,200 retail teams across India and Southeast Asia. In a six-month study with 42 customers, teams using the new Guided Setup finished onboarding in an average of 9 days, down from 14.5 days with the previous manual process.

The biggest change was the data-mapping step. Guided Setup detects 87% of column mappings automatically, so analysts only confirm exceptions. "We expected to spend two weeks on mapping and it was done in an afternoon," said Meera Shah, Head of Operations at Kiran Retail, which runs 64 stores in Gujarat.

Guided Setup also added a pre-built library of 30 retail dashboards, including sell-through, stock cover and footfall conversion. Customers who adopted at least five dashboards in the first month were 2.4 times more likely to renew.

Pricing has not changed: Guided Setup is included in the Growth plan at ₹24,000 per month, and the Starter plan remains ₹8,000 per month for teams of up to five users. Support is available in English, Hindi and Gujarati.

Northwind plans to extend Guided Setup to wholesale and pharmacy customers by March 2027.`;

// ---------------------------------------------------------------- helpers
function toast(msg, ms = 2800) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms); }
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
  return data;
}
const cls = (v) => (v >= 80 ? "good" : v >= 55 ? "warn" : "bad");
const list = (s) => String(s || "").split(",").map((x) => x.trim()).filter(Boolean);

function showView(name) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  $$("#main-tabs .tab").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  if (name === "jobs") renderJobs();
}
$$("#main-tabs .tab").forEach((b) => (b.onclick = () => showView(b.dataset.view)));

// ---------------------------------------------------------------- setup
$$("#source-mode .seg-btn").forEach((b) => (b.onclick = () => {
  $$("#source-mode .seg-btn").forEach((x) => x.classList.toggle("active", x === b));
  $("#text-wrap").hidden = b.dataset.mode !== "text"; $("#url-wrap").hidden = b.dataset.mode !== "url";
}));
function sourceStats() {
  const t = $("#f-text").value; const words = t.split(/\s+/).filter(Boolean).length;
  const nums = (t.match(/\d[\d,.]*%?/g) || []).length;
  $("#source-stats").textContent = t ? `${words} words · ${nums} numbers found · ~${Math.max(1, Math.round(t.split(/[.!?]+/).length - 1))} sentences` : "";
}
$("#f-text").addEventListener("input", sourceStats);
function readVoice() {
  return { name: $("#v-name").value.trim(), tone: $("#v-tone").value.trim(), pov: $("#v-pov").value, emoji: $("#v-emoji").value, reading_level: $("#v-reading").value.trim(), audience: $("#v-audience").value.trim(), preferred: list($("#v-preferred").value), banned: list($("#v-banned").value) };
}
function fillVoice(v) {
  $("#v-name").value = v.name || ""; $("#v-tone").value = v.tone || ""; $("#v-pov").value = v.pov || "we"; $("#v-emoji").value = v.emoji || "none";
  $("#v-reading").value = v.reading_level || ""; $("#v-audience").value = v.audience || "";
  $("#v-preferred").value = Array.isArray(v.preferred) ? v.preferred.join(", ") : v.preferred || "";
  $("#v-banned").value = Array.isArray(v.banned) ? v.banned.join(", ") : v.banned || "";
}
$("#load-sample").onclick = () => { $("#f-title").value = "Northwind Analytics cut onboarding time by 38%"; $("#f-text").value = SAMPLE_TEXT; fillVoice(SAMPLE_VOICE); sourceStats(); $$("#source-mode .seg-btn")[0].click(); toast("Sample case study and voice loaded"); };

async function loadVoices() {
  const vs = await api("/api/voices");
  $("#voice-select").innerHTML = `<option value="">Saved profiles…</option>` + vs.map((v) => `<option value="${esc(v.id)}">${esc(v.name || "Unnamed")}</option>`).join("");
  $("#voice-select")._data = vs;
}
$("#voice-select").onchange = (e) => { const v = ($("#voice-select")._data || []).find((x) => x.id === e.target.value); if (v) { fillVoice(v); toast(`Loaded “${v.name}”`); } };
$("#voice-save").onclick = async () => { const v = readVoice(); if (!v.name) return toast("Give the profile a name first"); const sel = $("#voice-select").value; if (sel) v.id = sel; await api("/api/voices", { method: "POST", body: JSON.stringify(v) }); await loadVoices(); toast("Voice profile saved"); };

// ---------------------------------------------------------------- run
$("#run-btn").onclick = async () => {
  const text = $("#f-text").value.trim(); const url = $("#f-url").value.trim();
  const useUrl = $$("#source-mode .seg-btn")[1].classList.contains("active");
  if (useUrl ? !url : !text) return toast(useUrl ? "Enter a page URL" : "Paste the approved source text first");
  const platforms = $$(".chips input:checked").map((i) => i.value);
  if (!platforms.length) return toast("Pick at least one output");
  const overlay = $("#overlay"); overlay.hidden = false; const steps = $$("#ov-steps li"); steps.forEach((s) => (s.className = ""));
  let i = 0; steps[0].className = "now";
  const tick = setInterval(() => { if (i < steps.length - 1) { steps[i].className = "done"; i++; steps[i].className = "now"; } }, state.status?.llm ? 7000 : 400);
  $("#run-btn").disabled = true;
  try {
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify({ text: useUrl ? "" : text, url: useUrl ? url : "", title: $("#f-title").value.trim(), voice: readVoice(), platforms }) });
    setJob(job); showView("workspace");
    toast(`${Object.keys(job.drafts).length} drafts ready · ${job.facts.length} facts traced`);
  } catch (e) { toast(e.message, 5000); }
  finally { clearInterval(tick); overlay.hidden = true; $("#run-btn").disabled = false; }
};

// ---------------------------------------------------------------- workspace
function setJob(job) {
  state.job = job; state.dirty = false;
  if (!job.drafts[state.platform]) state.platform = Object.keys(job.drafts)[0];
  $$("#main-tabs .tab[disabled]").forEach((b) => (b.disabled = false));
  $("#export-menu").hidden = false;
  $("#exp-md").href = `/api/jobs/${job.id}/export.md`; $("#exp-json").href = `/api/jobs/${job.id}/export.json`;
  $("#ws-title").textContent = job.title || "Untitled source";
  $("#ws-meta").textContent = `${job.source.word_count} words · ${job.source.sentences.length} sentences · ${job.facts.length} facts (${job.fact_mode}) · ${job.source.numbers.length} numbers guarded`;
  renderScores(); renderSource(); renderFacts(); renderMatrix(); renderPlatformTabs(); renderDraft();
}
function renderScores() {
  const j = state.job; const d = j.drafts[state.platform];
  $("#scores").innerHTML = [["Overall", j.overall], ["Traceability", d.trace.score], ["Brand voice", d.voice.score], ["Fact coverage", Math.round(d.trace.coverage * 100)]]
    .map(([l, v]) => `<div class="score"><span class="score-label">${l}</span><span class="score-val ${cls(v)}">${v}</span></div>`).join("");
}
$$(".ptab").forEach((b) => (b.onclick = () => { $$(".ptab").forEach((x) => x.classList.toggle("active", x === b)); ["source", "facts", "matrix"].forEach((k) => ($("#" + k + "-body").hidden = k !== b.dataset.ptab)); }));

function renderSource() {
  const src = state.job.source;
  const cited = new Set(); const d = state.job.drafts[state.platform];
  d.units.forEach((u) => (u.source_sentences || []).forEach((s) => cited.add(s)));
  const byPara = {};
  src.sentences.forEach((s) => (byPara[s.paragraph] ||= []).push(s));
  $("#source-body").innerHTML = `<div class="src-stats"><span>${src.numbers.length} numbers</span><span>${src.entities.length} names</span><span>underline = cited by this draft</span></div>` +
    Object.values(byPara).map((sents) => `<p class="src-para">` + sents.map((s) => `<span class="sent ${cited.has(s.id) ? "cited" : ""}" data-sid="${s.id}"><span class="num">${s.id}</span>${esc(s.text)} </span>`).join("") + `</p>`).join("");
  $$("#source-body .sent").forEach((el) => (el.onclick = () => { highlight({ sentences: [el.dataset.sid] }); const units = state.job.drafts[state.platform].units.map((u, i) => [u, i]).filter(([u]) => (u.source_sentences || []).includes(el.dataset.sid)); if (units.length) $(`.unit[data-i="${units[0][1]}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" }); units.forEach(([, i]) => $(`.unit[data-i="${i}"]`)?.classList.add("hlu")); }));
}
function renderFacts() {
  const d = state.job.drafts[state.platform]; const used = new Set(d.trace.used_facts || []);
  $("#facts-body").innerHTML = state.job.facts.map((f) => `<div class="fact ${used.has(f.id) ? "used" : ""}" data-fid="${f.id}"><span class="fid">${f.id}</span><div>${esc(f.fact)}<div class="fs">from ${f.sentence_ids.join(", ")}${used.has(f.id) ? " · used in this draft" : ""}</div></div><span class="fk">${esc(f.kind)}</span></div>`).join("") || `<div class="empty">No facts extracted.</div>`;
  $$("#facts-body .fact").forEach((el) => (el.onclick = () => { const f = state.job.facts.find((x) => x.id === el.dataset.fid); highlight({ sentences: f.sentence_ids, facts: [f.id] }); }));
}
function renderMatrix() {
  const d = state.job.drafts[state.platform]; const facts = state.job.facts;
  if (!facts.length) return ($("#matrix-body").innerHTML = `<div class="empty">No facts.</div>`);
  $("#matrix-body").innerHTML = `<p class="muted" style="margin-bottom:10px">Rows are lines of the ${LABEL[state.platform]} draft, columns are facts. ✓ cited and verified · ~ similar but not cited · ✗ cited but not similar.</p><div style="overflow:auto"><table class="matrix"><thead><tr><th>Line</th>${facts.map((f) => `<th title="${esc(f.fact)}">${f.id}</th>`).join("")}</tr></thead><tbody>` +
    d.units.map((u) => `<tr><td title="${esc(u.text)}">${esc(u.text)}</td>${facts.map((f) => {
      const v = (u.verified_facts || []).includes(f.id), m = (u.matched_facts || []).includes(f.id), b = (u.bad_claims || []).includes(f.id);
      return `<td class="${v ? "hit" : b ? "claimbad" : m ? "weak" : ""}">${v ? "✓" : b ? "✗" : m ? "~" : ""}</td>`;
    }).join("")}</tr>`).join("") + `</tbody></table></div>`;
}
function highlight({ sentences = [], facts = [] }) {
  $$(".sent.hl, .fact.hl").forEach((e) => e.classList.remove("hl")); $$(".unit.hlu").forEach((e) => e.classList.remove("hlu"));
  sentences.forEach((s) => $(`.sent[data-sid="${s}"]`)?.classList.add("hl"));
  facts.forEach((f) => $(`.fact[data-fid="${f}"]`)?.classList.add("hl"));
  const first = $(`.sent[data-sid="${sentences[0]}"]`); if (first && !$("#source-body").hidden) first.scrollIntoView({ block: "center", behavior: "smooth" });
}

function renderPlatformTabs() {
  $("#platform-tabs").innerHTML = Object.entries(state.job.drafts).map(([p, d]) => `<button class="ptab2 ptab ${p === state.platform ? "active" : ""}" data-p="${p}">${LABEL[p]} <span class="n">${d.score}</span></button>`).join("");
  $$("#platform-tabs .ptab").forEach((b) => (b.onclick = () => { if (state.dirty && !confirmDiscard()) return; state.platform = b.dataset.p; state.dirty = false; $("#recheck-btn").hidden = true; renderScores(); renderSource(); renderFacts(); renderMatrix(); renderPlatformTabs(); renderDraft(); }));
}
function confirmDiscard() { toast("Unchecked edits discarded"); return true; }

function unitHtml(u, i, extraCls = "") {
  const cites = u.verdict === "neutral" ? "" : (u.verified_facts?.length ? `<span class="cite">${u.verified_facts.join(" ")}</span>` : u.bad_claims?.length ? `<span class="cite bad">${u.bad_claims.join(" ")} ✗</span>` : u.matched_facts?.length ? `<span class="cite">~${u.matched_facts[0]}</span>` : "");
  const issue = u.bad_numbers?.length ? `<div class="issue">Number not in source: ${u.bad_numbers.join(", ")}</div>` : u.voice_issues?.length ? `<div class="issue">${esc(u.voice_issues.join(", "))}</div>` : "";
  return `<div class="unit ${u.verdict} ${u.role} ${extraCls}" data-i="${i}" title="fact sim ${u.fact_similarity} · source sim ${u.source_similarity}"><span class="text" contenteditable="true" spellcheck="false">${esc(u.text)}</span>${cites}${issue}</div>`;
}
function renderDraft() {
  const d = state.job.drafts[state.platform]; const p = state.platform;
  let html = "";
  if (p === "linkedin") {
    html = `<div class="preview"><div class="post-card"><div class="post-author"><div class="avatar"></div><div><b>${esc(state.job.voice_profile?.name || "Your company")}</b><small>${esc(state.job.voice_profile?.audience || "")} · now</small></div></div>` +
      d.units.map((u, i) => unitHtml(u, i)).join("") + `<div class="hashtags">${(d.hashtags || []).map((h) => "#" + esc(h)).join(" ")}</div></div></div>`;
  } else if (p === "instagram") {
    const slides = d.units.map((u, i) => [u, i]).filter(([u]) => u.role === "slide");
    const rest = d.units.map((u, i) => [u, i]).filter(([u]) => u.role !== "slide");
    html = `<div class="preview"><div class="slides">` + slides.map(([u, i]) => `<div class="slide ${u.verdict}" data-i="${i}"><span class="sn">${u.meta.slide}/${slides.length}${u.verified_facts?.length ? " · " + u.verified_facts.join(" ") : ""}</span><span class="text" contenteditable="true" spellcheck="false">${esc(u.text)}</span></div>`).join("") + `</div><div class="post-card">` +
      rest.map(([u, i]) => unitHtml(u, i)).join("") + `<div class="hashtags">${(d.hashtags || []).map((h) => "#" + esc(h)).join(" ")}</div></div></div>`;
  } else {
    const title = d.units.find((u) => u.role === "title");
    html = `<div class="preview">` + (title ? `<div class="video-title">${esc(title.text)}</div>` : "") +
      d.units.map((u, i) => [u, i]).filter(([u]) => u.role === "scene").map(([u, i]) => `<div class="scene"><div class="t">${esc(u.meta.time)}</div><div>${unitHtml(u, i)}<div class="os">On screen: <b>${esc(u.meta.on_screen)}</b></div>${u.meta.visual ? `<div class="vis">${esc(u.meta.visual)}</div>` : ""}</div></div>`).join("") +
      d.units.map((u, i) => [u, i]).filter(([u]) => u.role === "cta").map(([u, i]) => unitHtml(u, i)).join("") + `</div>`;
  }
  $("#draft-body").innerHTML = html;
  $$("#draft-body [data-i]").forEach((el) => {
    const u = d.units[+el.dataset.i];
    el.addEventListener("mouseenter", () => highlight({ sentences: u.source_sentences || [], facts: u.verified_facts?.length ? u.verified_facts : u.matched_facts || [] }));
    $(".text", el)?.addEventListener("input", () => { state.dirty = true; $("#recheck-btn").hidden = false; });
  });
  renderChecks(d);
}
function renderChecks(d) {
  const t = d.trace, v = d.voice;
  const li = (arr, c) => arr.map((x) => `<li class="${c}">${esc(x)}</li>`).join("");
  $("#checks").innerHTML = `
    <div class="check-box"><h3>Traceability <span class="pill ${cls(t.score)}">${t.score}</span></h3>
      <div class="kv"><span>supported</span><span>${t.supported}</span><span>partial</span><span>${t.partial}</span><span>unsupported</span><span>${t.unsupported}</span><span>no claim</span><span>${t.neutral}</span><span>facts used</span><span>${(t.used_facts || []).length} / ${state.job.facts.length}</span><span>mode</span><span>${esc(d.mode)}${d.revisions ? ` · ${d.revisions} auto-revision` : ""}</span></div>
      ${t.problems.length ? `<ul>${li(t.problems, "bad")}</ul>` : `<div class="ok-line">Every claim traces back to the source.</div>`}</div>
    <div class="check-box"><h3>Brand voice <span class="pill ${cls(v.score)}">${v.score}</span></h3>
      <div class="tone-bars">${Object.entries(v.tone).map(([k, p]) => `<div class="tone-row ${k === v.target_tone ? "target" : ""}"><span>${k}${k === v.target_tone ? " (target)" : ""}</span><div class="bar"><div class="fill" style="width:${p * 100}%"></div></div><span class="n">${Math.round(p * 100)}%</span></div>`).join("")}</div>
      <div class="kv"><span>reading ease</span><span>${v.readability.flesch} (grade ${v.readability.grade})</span><span>avg sentence</span><span>${v.readability.avg_sentence_len} words</span><span>length</span><span>${v.chars} chars · ${v.hashtag_count} tags · ${v.emoji_count} emoji</span><span>preferred used</span><span>${v.preferred_used.join(", ") || "none"}</span></div>
      ${v.problems.length || v.warnings.length ? `<ul>${li(v.problems, "bad")}${li(v.warnings, "warn")}</ul>` : `<div class="ok-line">On brand.</div>`}</div>`;
}

$("#recheck-btn").onclick = async () => {
  const texts = {}; $$("#draft-body [data-i]").forEach((el) => { const t = $(".text", el); if (t) texts[el.dataset.i] = t.textContent.trim(); });
  $("#recheck-btn").disabled = true;
  try { const job = await api(`/api/jobs/${state.job.id}/drafts/${state.platform}`, { method: "PUT", body: JSON.stringify({ texts }) }); setJob(job); $("#recheck-btn").hidden = true; toast("Edits re-checked against the source"); }
  catch (e) { toast(e.message); } finally { $("#recheck-btn").disabled = false; }
};
$("#regen-btn").onclick = async () => {
  $("#regen-btn").disabled = true; $("#regen-btn").textContent = "Writing…";
  try { const job = await api(`/api/jobs/${state.job.id}/drafts/${state.platform}/regenerate`, { method: "POST", body: JSON.stringify({ instructions: $("#regen-instr").value.trim() }) }); setJob(job); toast(`${LABEL[state.platform]} draft regenerated`); }
  catch (e) { toast(e.message); } finally { $("#regen-btn").disabled = false; $("#regen-btn").textContent = "↻ Regenerate"; }
};

// ---------------------------------------------------------------- jobs
async function renderJobs() {
  const jobs = await api("/api/jobs");
  $("#jobs-list").innerHTML = jobs.map((j) => `<div class="job-row"><div><div style="font-weight:500">${esc(j.title)}</div><div class="m">${j.words} words · ${(j.platforms || []).map((p) => LABEL[p]).join(", ")}</div></div><span class="pill ${cls(j.overall)}">${j.overall}</span><span class="m">${new Date(j.updated_at * 1000).toLocaleString()}</span><div class="row"><button class="btn small" data-open="${j.id}">Open</button><button class="btn small ghost" data-del="${j.id}">Delete</button></div></div>`).join("") || `<div class="empty">No jobs yet. Run the pipeline on a source.</div>`;
  $$("[data-open]").forEach((b) => (b.onclick = async () => { setJob(await api(`/api/jobs/${b.dataset.open}`)); showView("workspace"); }));
  $$("[data-del]").forEach((b) => (b.onclick = async () => { await api(`/api/jobs/${b.dataset.del}`, { method: "DELETE" }); renderJobs(); }));
}

// ---------------------------------------------------------------- export + boot
$("#export-btn").onclick = (e) => { e.stopPropagation(); $("#export-list").hidden = !$("#export-list").hidden; };
document.addEventListener("click", () => ($("#export-list").hidden = true));
(async function boot() {
  try {
    const s = await api("/api/status"); state.status = s;
    $("#engine").classList.add(s.llm ? "on" : "off");
    $("#engine-text").textContent = s.llm ? `Claude · ${s.model}` : "Offline mode · set ANTHROPIC_API_KEY";
  } catch { $("#engine-text").textContent = "API unreachable"; }
  loadVoices();
  $("#load-sample").click();
})();

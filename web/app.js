// vrfu-ai — frontend
const $  = sel => document.querySelector(sel);
const $$ = sel => Array.from(document.querySelectorAll(sel));

const state = {
  character: localStorage.getItem("character") || null,
  page_active: localStorage.getItem("page_active") || "generation",
  // Review state
  view:    "output",
  batch:   "all",
  filter:  "all",
  artist:  "all",
  page:    1,
  perPage: 50,
  total:   0,
  pages:   1,
  showUpscaled: localStorage.getItem("showUpscaled") !== "false",  // default: true
  upscaleScale: Math.max(1.0, Math.min(3.0, parseFloat(localStorage.getItem("upscaleScale")) || 2.0)),
  search: "",
  // Run polling
  runPoll: null,
};

// Tags filtered out of the per-image scene-tag preview because they're
// presentation/framing/quality noise rather than content.
// Per-character noise (trigger_word + character_tags) is filtered dynamically
// inside extractSceneTags() using _charInfo. Outfit-bundle tags are also
// stripped dynamically from _charInfo.outfits so a tag like "white kimono"
// disappears from previews of {outfit}-using prompts.
const NOISY_TAGS = new Set([
  // Subject count
  "1girl", "1boy", "solo", "2girls", "multiple girls", "multiple views",
  // Quality / aesthetic / resolution / year
  "masterpiece", "best quality", "amazing quality", "very aesthetic", "aesthetic",
  "displeasing", "very displeasing", "worst aesthetic", "very awa",
  "absurdres", "highres", "lowres",
  "newest", "recent", "mid", "early", "old", "oldest",
  "year 2024", "year 2023", "year 2022", "year 2021", "year 2020",
  // Rating
  "safe", "sensitive", "questionable", "nsfw", "explicit",
  // Style anchors
  "anime coloring", "anime screencap", "cel shading", "flat color", "2d", "3d",
  "anime", "official art",
  // Composition / framing / camera
  "looking at viewer", "looking away", "looking back", "looking up", "looking down",
  "from above", "from below", "from behind", "from side", "from front",
  "full body", "upper body", "lower body", "half body", "cowboy shot",
  "portrait", "close-up", "wide shot", "long shot",
  "foot focus", "face focus", "body focus", "hair focus", "head focus",
  "head out of frame",
  "facing viewer", "three quarter view", "side view", "profile",
  "dutch angle", "fisheye",
  // Lighting / atmosphere (presentation, not content)
  "soft lighting", "hard lighting", "rim lighting", "dappled sunlight",
  "volumetric lighting", "lens flare", "depth of field", "bokeh",
  "golden hour", "blue hour", "moonlight", "sunlight", "lantern light",
  "soft window light", "soft morning light", "soft natural light",
  // Quality negatives that occasionally leak forward
  "bad anatomy", "bad hands", "deformed", "cropped head", "cropped feet",
  "worst quality", "low quality", "bad quality",
]);

// ── Generic ────────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}
async function postJSON(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(body),
  });
}
let _toastTimer;
function toast(msg, ms = 2400) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.add("hidden"), ms);
}
function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, ch => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;",
  }[ch]));
}

// ── Page switching ─────────────────────────────────────────────────────────
function switchPage(page) {
  state.page_active = page;
  localStorage.setItem("page_active", page);
  $$(".page-btn").forEach(b => b.classList.toggle("active", b.dataset.page === page));
  $$(".page").forEach(p => p.classList.add("hidden"));
  $(`#page-${page}`).classList.remove("hidden");

  if (page === "generation") {
    loadQueue();
    pollRunStatus();
    if (!state.runPoll) state.runPoll = setInterval(pollRunStatus, 2500);
  } else {
    if (state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; }
  }
  if (page === "review") {
    Promise.all([loadBatches(), loadArtists()]).then(loadImages);
  }
  if (page === "activity") {
    loadActivity();
  }
  if (page === "docs") {
    loadDocsList();
  }
}

// ── Docs viewer ──────────────────────────────────────────────────────────
let _docsList = [];
async function loadDocsList() {
  try {
    const r = await api("/api/docs");
    _docsList = r.docs || [];
    const sb = $("#docs-sidebar");
    sb.innerHTML = "";
    if (!_docsList.length) {
      sb.innerHTML = `<p class="muted">no .md files in docs/</p>`;
      return;
    }
    // Sort with README first, then alphabetical
    _docsList.sort((a, b) => {
      if (a.name.toLowerCase() === "readme") return -1;
      if (b.name.toLowerCase() === "readme") return 1;
      return a.name.localeCompare(b.name);
    });
    _docsList.forEach(d => {
      const b = document.createElement("button");
      b.dataset.slug = d.name;
      b.textContent = d.name;
      b.title = d.filename;
      b.addEventListener("click", () => loadDoc(d.name));
      sb.appendChild(b);
    });
    // Auto-open the first one (usually README)
    if (_docsList.length) loadDoc(_docsList[0].name);
  } catch (e) {
    console.warn("docs list failed", e);
  }
}
async function loadDoc(slug) {
  try {
    const r = await api(`/api/docs/${encodeURIComponent(slug)}`);
    if (!r.ok) return;
    // Highlight active link in sidebar
    $$("#docs-sidebar button").forEach(b =>
      b.classList.toggle("active", b.dataset.slug === slug));
    // Render markdown via marked.js (loaded in index.html)
    const html = (typeof marked !== "undefined")
      ? marked.parse(r.content)
      : `<pre>${escapeHTML(r.content)}</pre>`;
    $("#docs-content").innerHTML = html;
    $("#docs-content").scrollTop = 0;
  } catch (e) {
    console.warn("doc load failed", e);
  }
}

// ── Characters ─────────────────────────────────────────────────────────────
async function loadCharacters() {
  const { characters } = await api("/api/characters");
  const sel = $("#character");
  sel.innerHTML = "";
  characters.forEach(c => {
    const o = document.createElement("option");
    o.value = c; o.textContent = c;
    sel.appendChild(o);
  });
  if (!state.character || !characters.includes(state.character)) {
    state.character = characters[0] || null;
  }
  if (state.character) sel.value = state.character;
}

// ── Generation: model info banner ────────────────────────────────────────
async function loadCharacterInfo() {
  if (!state.character) return;
  try {
    const info = await api(`/api/character-info?character=${encodeURIComponent(state.character)}`);
    _charInfo = info;
    $("#model-name").textContent   = info.checkpoint     || "—";
    $("#lora-name").textContent    = info.character_lora ? `${info.character_lora} @ ${info.lora_weight}` : "—";
    $("#trigger-name").textContent = info.trigger_word   || "—";
  } catch (e) { console.warn("character-info failed", e); }
  // Cache-bust so the thumbnail refreshes after Organize / new generations.
  $("#character-thumb").src =
    `/api/character/thumbnail?character=${encodeURIComponent(state.character)}&t=${Date.now()}`;
}

// ── Generation: queue ─────────────────────────────────────────────────────
async function loadQueue() {
  if (!state.character) return;
  loadCharacterInfo();   // refresh model/LoRA banner alongside the queue
  const { queue } = await api(`/api/queue?character=${encodeURIComponent(state.character)}`);
  $("#queue-count").textContent = queue.length;
  const tbody = $("#queue-tbody");
  tbody.innerHTML = "";
  // Find which entry (if any) is currently being generated
  let activeLabel = null;
  if (_runStatusCache && _runStatusCache.state === "running") {
    activeLabel = _runStatusCache.current_label || null;
  }

  queue.forEach((entry, idx) => {
    const tr = document.createElement("tr");
    const dim = (entry.width || 1024) + "×" + (entry.height || 1024);
    const promptTrunc = (entry.prompt || "").slice(0, 90)
      + ((entry.prompt || "").length > 90 ? "…" : "");
    const lbl = escapeHTML(entry.label);
    const isActive = entry.label === activeLabel;
    const idxLabel = isActive ? "▶️" : (idx + 1);
    if (isActive) tr.classList.add("queue-row-active");

    const upBtn   = idx === 0 ? "" : `<button class="row-btn" data-action="up"   data-label="${lbl}" title="Move up">▲</button>`;
    const downBtn = idx === queue.length - 1 ? "" : `<button class="row-btn" data-action="down" data-label="${lbl}" title="Move down">▼</button>`;
    const topBtn  = idx === 0 ? "" : `<button class="row-btn" data-action="top"  data-label="${lbl}" title="Move to top">⤒</button>`;

    tr.innerHTML = `
      <td class="muted">${idxLabel}</td>
      <td class="mono">${lbl}${isActive ? ' <span class="active-badge">generating</span>' : ""}</td>
      <td class="muted">${dim}</td>
      <td class="prompt-cell" title="${escapeHTML(entry.prompt || "")}">${escapeHTML(promptTrunc)}</td>
      <td class="row-actions">
        ${topBtn}${upBtn}${downBtn}
        <button class="row-btn" data-action="edit"      data-label="${lbl}" title="Edit">✏️</button>
        <button class="row-btn" data-action="duplicate" data-label="${lbl}" title="Duplicate">📋</button>
        <button class="row-btn row-btn-danger" data-action="delete" data-label="${lbl}" title="Delete">🗑</button>
      </td>`;
    tbody.appendChild(tr);
  });

  // Reorder buttons
  async function reorder(label, dir) {  // dir = "up" | "down" | "top"
    const labels = queue.map(e => e.label);
    const i = labels.indexOf(label);
    if (i < 0) return;
    if (dir === "top") {
      labels.splice(i, 1); labels.unshift(label);
    } else {
      const j = dir === "up" ? i - 1 : i + 1;
      if (j < 0 || j >= labels.length) return;
      [labels[i], labels[j]] = [labels[j], labels[i]];
    }
    await postJSON("/api/queue/reorder", { character: state.character, labels });
    loadQueue();
  }
  ["up", "down", "top"].forEach(dir => {
    tbody.querySelectorAll(`button[data-action="${dir}"]`).forEach(btn => {
      btn.addEventListener("click", () => reorder(btn.dataset.label, dir));
    });
  });
  // Wire up row actions
  tbody.querySelectorAll('button[data-action="delete"]').forEach(btn => {
    btn.addEventListener("click", () => deleteFromQueue([btn.dataset.label]));
  });
  tbody.querySelectorAll('button[data-action="duplicate"]').forEach(btn => {
    btn.addEventListener("click", async () => {
      const r = await postJSON("/api/queue/duplicate", {
        character: state.character, label: btn.dataset.label,
      });
      if (r.ok) { toast(`Duplicated → "${r.label}"`); loadQueue(); }
      else { toast("Duplicate failed: " + r.err); }
    });
  });
  tbody.querySelectorAll('button[data-action="edit"]').forEach(btn => {
    btn.addEventListener("click", () => {
      const label = btn.dataset.label;
      const entry = queue.find(e => e.label === label);
      if (!entry) return;
      addPromptModalOpen({
        editingLabel: label,
        label:        entry.label,
        prompt:       entry.prompt,
        width:        entry.width,
        height:       entry.height,
      });
    });
  });
}

async function deleteFromQueue(labels) {
  await postJSON("/api/queue/delete", { character: state.character, labels });
  toast(`Removed ${labels.length} entry${labels.length !== 1 ? "ies" : "y"}`);
  loadQueue();
}

// Resolution presets
const RESOLUTIONS = {
  square:    { w: 1024, h: 1024 },
  portrait:  { w: 832,  h: 1216 },
  landscape: { w: 1216, h: 832  },
};
function resolutionFromDims(w, h) {
  if (!w || !h)         return "square";
  if (w === h)          return "square";
  if (w < h)            return "portrait";
  return "landscape";
}

// Strip auto-prepended prompt prefixes so the modal shows only the user-editable part
let _charInfo = null;   // last loaded /api/character-info
function stripUserPrompt(fullPrompt) {
  if (!_charInfo || !fullPrompt) return fullPrompt || "";
  let p = fullPrompt;
  const tryStrip = prefix => {
    if (prefix && p.toLowerCase().startsWith((prefix + ", ").toLowerCase())) {
      p = p.slice(prefix.length + 2);
    }
  };
  tryStrip(_charInfo.base_positive);
  tryStrip(_charInfo.trigger_word);
  tryStrip(_charInfo.character_tags);
  return p;
}

// When set, the modal saves via /api/queue/update instead of /api/queue/add
let _editingLabel = null;

function addPromptModalOpen(prefill) {
  // prefill: { label?, prompt?, width?, height?, editingLabel? }   (seeds are always random)
  prefill = prefill || {};
  _editingLabel = prefill.editingLabel || null;
  $("#add-label").value  = prefill.label  || "";
  $("#add-prompt").value = prefill.prompt || "";
  // Pick resolution radio
  const res = resolutionFromDims(prefill.width, prefill.height);
  $$("#modal-add input[name=resolution]").forEach(r => r.checked = (r.value === res));
  // Title + button label depend on mode
  if (_editingLabel) {
    $("#modal-add-title").textContent = `Edit prompt — ${_editingLabel}`;
    $("#add-save").textContent = "Save changes";
  } else if (prefill.prompt) {
    $("#modal-add-title").textContent = "Remix prompt → add to queue";
    $("#add-save").textContent = "Add to queue";
  } else {
    $("#modal-add-title").textContent = "Add prompt";
    $("#add-save").textContent = "Add to queue";
  }
  $("#modal-add").classList.remove("hidden");
  populateQuickArtists();
  setTimeout(() => $("#add-prompt").focus(), 50);
}

async function populateQuickArtists() {
  // Top 6 artists from current character's stats
  try {
    const s = await api(`/api/stats?character=${encodeURIComponent(state.character)}`);
    const wrap = $("#quick-artists");
    wrap.innerHTML = "";
    (s.top_artists || []).slice(0, 6).forEach(([name, score]) => {
      const b = document.createElement("button");
      b.className = "chip-btn";
      b.dataset.tag = `artist:${name}`;
      b.textContent = name;
      b.title = `score ${score}`;
      wrap.appendChild(b);
    });
  } catch (e) {}
  populateQuickOutfits();
  populateQuickPopular();
}

// Outfit chips: one per named outfit in the character's config.yaml.
// Inserts the {outfit} / {outfit:name} placeholder, NOT the literal tags —
// generate.py expands the placeholder server-side so prompts stay short.
function populateQuickOutfits() {
  const wrap = $("#quick-outfits");
  if (!wrap) return;
  wrap.innerHTML = "";
  const outfits = (_charInfo && _charInfo.outfits) || {};
  const names = Object.keys(outfits);
  if (!names.length) {
    wrap.innerHTML = `<span class="muted">no outfits defined in config.yaml</span>`;
    return;
  }
  // 'default' goes first; rest alphabetical
  names.sort((a, b) => a === "default" ? -1 : b === "default" ? 1 : a.localeCompare(b));
  for (const name of names) {
    const b = document.createElement("button");
    b.className = "chip-btn";
    b.dataset.tag = name === "default" ? "{outfit}" : `{outfit:${name}}`;
    b.textContent = name;
    b.title = outfits[name];   // hover shows the actual tag bundle
    wrap.appendChild(b);
  }
  // Always-useful state chip alongside named outfits
  const nudeBtn = document.createElement("button");
  nudeBtn.className = "chip-btn";
  nudeBtn.dataset.tag = "nude";
  nudeBtn.textContent = "nude";
  wrap.appendChild(nudeBtn);
}

// Popular chips: top tags from the character's liked images, computed by
// the server. Refreshed on every modal open + after Organize is clicked.
function populateQuickPopular() {
  const wrap = $("#quick-popular");
  if (!wrap) return;
  wrap.innerHTML = "";
  const popular = (_charInfo && _charInfo.popular_tags) || [];
  if (!popular.length) {
    wrap.innerHTML = `<span class="muted">no liked images yet — vote ❤️/👍 then Organize</span>`;
    return;
  }
  for (const { tag, count } of popular) {
    const b = document.createElement("button");
    b.className = "chip-btn";
    b.dataset.tag = tag;
    b.textContent = tag;
    b.title = `${count}× in liked images`;
    wrap.appendChild(b);
  }
}

async function addPromptModalSave() {
  const label  = $("#add-label").value.trim();
  const prompt = $("#add-prompt").value.trim();
  if (!prompt) { toast("Prompt is required"); return; }
  const resVal = ($$("#modal-add input[name=resolution]:checked")[0] || {}).value || "square";
  const { w, h } = RESOLUTIONS[resVal];

  if (_editingLabel) {
    // UPDATE existing entry
    const fields = { prompt, width: w, height: h };
    if (label && label !== _editingLabel) fields.label = label;
    const r = await postJSON("/api/queue/update", {
      character: state.character,
      label:     _editingLabel,
      fields:    fields,
    });
    if (r.ok) {
      toast(`Updated "${r.label}"`);
      _editingLabel = null;
      $("#modal-add").classList.add("hidden");
      loadQueue();
    } else {
      toast("Update failed: " + r.err);
    }
    return;
  }

  // ADD new entry (prepended on the server side)
  const body = {
    character: state.character,
    label:     label || "untitled",
    prompt,
    width:     w,
    height:    h,
  };
  const r = await postJSON("/api/queue/add", body);
  toast(`Added "${r.label}"`);
  $("#modal-add").classList.add("hidden");
  loadQueue();
}

// Append a tag to the prompt textarea (no double-add)
function appendTagToPrompt(tag) {
  const ta = $("#add-prompt");
  const cur = ta.value.trim();
  // Check if any of the tag's comma-separated parts is already present (case-insensitive)
  const tagParts = tag.split(",").map(t => t.trim().toLowerCase());
  const curTags  = cur.split(",").map(t => t.trim().toLowerCase());
  const newParts = tagParts.filter(t => !curTags.includes(t));
  if (newParts.length === 0) { toast("Already in prompt"); return; }
  const newTag = newParts.join(", ");
  ta.value = cur ? `${cur}, ${newTag}` : newTag;
  ta.focus();
}
async function importYAMLModalSave() {
  const yaml = $("#import-yaml").value;
  if (!yaml.trim()) { toast("Paste some YAML first"); return; }
  try {
    const r = await postJSON("/api/queue/import", { character: state.character, yaml });
    if (r.ok) {
      toast(`Imported ${r.added} prompts`);
      $("#modal-import").classList.add("hidden");
      $("#import-yaml").value = "";
      loadQueue();
    } else { toast("Import failed: " + r.err); }
  } catch (e) { toast("Import error: " + e.message); }
}
async function clearQueue() {
  if (!confirm("Clear the entire queue? This cannot be undone.")) return;
  await postJSON("/api/queue/clear", { character: state.character, confirm: true });
  toast("Queue cleared");
  loadQueue();
}

// ── Generation: run controls ─────────────────────────────────────────────
// Tracks what kind of job is currently active in the banner: "generate" | "upscale" | null
let _activeJob = null;

async function startRun() {
  const r = await postJSON("/api/run/start", { character: state.character });
  if (!r.ok) { toast("Cannot start: " + r.err); return; }
  toast("Run started");
  _activeJob = "generate";
  pollRunStatus();
}
async function startUpscaleFromBanner() {
  const r = await postJSON("/api/upscale", { character: state.character, scale: state.upscaleScale });
  if (!r.ok) { toast("Cannot start: " + r.err); return; }
  toast(`Upscale started @ ${state.upscaleScale}×`);
  _activeJob = "upscale";
  pollRunStatus();
}
async function startTraining() {
  if (!confirm(`Start training a LoRA for "${state.character}"?\n\nThis can take 1-3 hours depending on steps. GPU will be busy the whole time — generation and upscaling will be blocked.`)) return;
  // Snapshot the chain-to-gen toggle state at click time and pass it with the
  // start request, so the server's chain flag can't drift out of sync with what
  // the user sees in the UI.
  const chainToGen = $("#chain-after-training")?.checked || false;
  const r = await postJSON("/api/training/start", {
    character: state.character,
    chain_to_gen: chainToGen,
  });
  if (!r.ok) { toast("Cannot start: " + r.err); return; }
  toast(chainToGen ? "🎓 Training started — gen will auto-start after" : "🎓 Training started");
  _activeJob = "training";
  pollRunStatus();
}
async function stopRun() {
  if (!confirm("Stop the current job?")) return;
  if (_activeJob === "upscale") {
    const r = await postJSON("/api/tool/stop", { tool: "upscale" });
    toast(r.ok ? "Stop signal sent to upscaler" : "Stop error: " + r.err);
  } else if (_activeJob === "training") {
    const r = await postJSON("/api/training/stop", {});
    toast(r.ok ? "Stop signal sent to training" : "Stop error: " + r.err);
  } else {
    const r = await postJSON("/api/run/stop", {});
    toast(r.ok ? "Stop signal sent to generator" : "Stop error: " + r.err);
  }
  pollRunStatus();
}

let _runStatusCache = null;
async function pollRunStatus() {
  try {
    // Probe ALL THREE endpoints — whichever is running drives the banner
    const [genStatus, upscaleStatus, trainStatus] = await Promise.all([
      api("/api/run/status").catch(() => ({state: "idle"})),
      api("/api/tool/status?tool=upscale").catch(() => ({state: "idle"})),
      api("/api/tool/status?tool=training").catch(() => ({state: "idle"})),
    ]);
    _runStatusCache = genStatus;

    const genRunning = genStatus.state === "running";
    const upRunning  = upscaleStatus.state === "running";
    const trRunning  = trainStatus.state === "running";

    let s, kind;
    if (genRunning) {
      s = genStatus; kind = "generate"; _activeJob = "generate";
    } else if (upRunning) {
      s = upscaleStatus; kind = "upscale"; _activeJob = "upscale";
    } else if (trRunning) {
      s = trainStatus; kind = "training"; _activeJob = "training";
    } else {
      // Pick whichever finished most recently for the "completed" message
      const recent = [genStatus, upscaleStatus, trainStatus]
        .filter(x => x.exit_code !== null && x.exit_code !== undefined)
        .sort((a, b) => (b.started_at || "").localeCompare(a.started_at || ""))[0];
      s = recent || {state: "idle"};
      kind = (s === genStatus) ? "generate" : (s === upscaleStatus) ? "upscale" : (s === trainStatus) ? "training" : "generate";
      _activeJob = null;
    }
    const isRunning = (s.state === "running");

    // Buttons: only one start button visible at a time, stop visible when something runs
    $("#run-start").classList.toggle("hidden", isRunning);
    $("#run-upscale").classList.toggle("hidden", isRunning);
    $("#run-train").classList.toggle("hidden", isRunning);
    $("#run-start").disabled   = isRunning;
    $("#run-upscale").disabled = isRunning;
    $("#run-train").disabled   = isRunning;
    $("#run-stop").classList.toggle("hidden", !isRunning);

    // Chain toggles
    $("#chain-toggle-wrap").classList.toggle("hidden", !upRunning);
    if (upRunning) $("#chain-after-upscale").checked = !!genStatus.chain_after_upscale;
    $("#chain-train-toggle-wrap").classList.toggle("hidden", !trRunning);
    // (chain_after_training flag is server-side only; we set it via the toggle change handler)

    // Status text adapts to job kind
    const labels = {
      generate: { running: "▶️ Generating", done: "✅ Generation done", err: "❌ Generation error" },
      upscale:  { running: "🔼 Upscaling",  done: "✅ Upscale done",     err: "❌ Upscale error" },
      training: { running: "🎓 Training",   done: "✅ Training done",   err: "❌ Training error" },
    }[kind] || { running: "Running", done: "Done", err: "Error" };
    let stateLabel;
    if (s.state === "running")       stateLabel = `${labels.running} for ${s.character || ""}`;
    else if (s.state === "completed") stateLabel = labels.done;
    else if (s.state === "error")     stateLabel = `${labels.err} (exit ${s.exit_code ?? "?"})`;
    else                              stateLabel = "Idle";
    $("#run-status").textContent = stateLabel;

    // Progress bar
    const pct = s.total ? Math.round(100 * s.current_index / s.total) : 0;
    $("#run-progress").style.width = pct + "%";
    $("#run-current-label").textContent = s.current_label
      ? `${s.current_index}/${s.total} — ${s.current_label}`
      : (isRunning ? "(loading model…)" : "—");

    // ETA
    if (isRunning && s.last_dur_s && s.total && s.current_index) {
      const remaining = (s.total - s.current_index) * s.last_dur_s;
      const mins = Math.round(remaining / 60);
      $("#run-eta").textContent = `~${mins} min remaining`;
    } else {
      $("#run-eta").textContent = "";
    }

    // Live thumbnail (only useful for generate)
    if (isRunning && kind === "generate" && s.character) {
      try {
        const li = await api(`/api/run/latest-image?character=${encodeURIComponent(s.character)}`);
        if (li.filename) {
          $("#run-preview").src = `/img/${s.character}/${li.filename}?t=${Date.now()}`;
          $("#run-preview").classList.remove("hidden");
        }
      } catch (e) {}
    } else if (!isRunning) {
      // Keep last frame, or hide for upscale
      if (kind === "upscale") $("#run-preview").classList.add("hidden");
    }

    // Log tail
    let log = "";
    if (kind === "generate") {
      const lg = await api("/api/run/log?tail=12");
      log = lg.log;
    } else if (kind === "upscale") {
      log = upscaleStatus.log_tail || "";
    } else if (kind === "training") {
      log = trainStatus.log_tail || "";
    }
    $("#run-log").textContent = log || "(no output yet)";

    // When upscale finishes, refresh review tab images so the new state shows
    if (!isRunning && kind === "upscale" && state.page_active === "review") {
      loadArtists(); loadImages();
    }

    // Live-refresh the queue table while generation is running
    // (generate.py removes the top entry after each successful image)
    if (isRunning && kind === "generate" && state.page_active === "generation") {
      // Only reload if the count would actually change to avoid useless DOM thrash
      const currentRows = document.querySelectorAll("#queue-tbody tr").length;
      const expectedRows = (s.total - s.current_index);
      if (currentRows !== expectedRows) loadQueue();
    }
  } catch (e) {
    console.warn("status poll failed", e);
  }
}

// ── Review: artists, batches, images, voting ────────────────────────────
async function loadBatches() {
  if (!state.character) return;
  const wrap = $("#batch-wrap");
  if (state.view !== "output") { wrap.style.display = "none"; return; }
  wrap.style.display = "";
  const { batches } = await api(`/api/batches?character=${encodeURIComponent(state.character)}`);
  const sel = $("#batch");
  sel.innerHTML = '<option value="all">All time</option><option value="latest">Latest batch</option>';
  Object.entries(batches).forEach(([id, b]) => {
    const o = document.createElement("option");
    o.value = id; o.textContent = `${id} (${b.count})`;
    sel.appendChild(o);
  });
  sel.value = state.batch;
}
async function loadArtists() {
  if (!state.character) return;
  const { artists, no_artist } = await api(
    `/api/artists?character=${encodeURIComponent(state.character)}&view=${state.view}`
  );
  const sel = $("#artist");
  sel.innerHTML = '<option value="all">All artists</option>';
  if (no_artist > 0) {
    const o = document.createElement("option");
    o.value = "no-artist"; o.textContent = `(no artist) (${no_artist})`;
    sel.appendChild(o);
  }
  artists.forEach(a => {
    const o = document.createElement("option");
    o.value = a.name; o.textContent = `${a.name} (${a.count})`;
    sel.appendChild(o);
  });
  if ([...sel.options].some(o => o.value === state.artist)) sel.value = state.artist;
  else { state.artist = "all"; sel.value = "all"; }
}

async function loadStats() {
  if (!state.character) return;
  const s = await api(`/api/stats?character=${encodeURIComponent(state.character)}`);
  const c = s.counts;
  $("#stat-counts").innerHTML = `
    <li><strong>${c.total}</strong> total images</li>
    <li><strong>${c.voted}</strong> voted (${c.total ? Math.round(c.voted / c.total * 100) : 0}%)</li>
    <li><strong>${c.super_liked || 0}</strong> 💜 super liked</li>
    <li><strong>${c.loved}</strong> ❤️ loved</li>
    <li><strong>${c.liked}</strong> 👍 liked</li>
    <li><strong>${c.disliked || 0}</strong> 👎 disliked</li>
    <li><strong>${c.style}</strong> 🎨 style liked</li>
    <li><strong>${c.prompt}</strong> 📍 prompt liked</li>
    <li><strong>${c.pose}</strong> 🤸 pose liked</li>
    <li><strong>${c.outfit}</strong> 👗 outfit liked</li>
    <li><strong>${c.anatomy_issue}</strong> ⚠️ anatomy issues</li>
    <li><strong>${c.with_comment}</strong> 💬 with comments</li>`;
  const fmt = arr => arr.length
    ? arr.map(([k, v]) => `<li><strong>${k}</strong> — ${v}</li>`).join("")
    : "<li><em>(none yet)</em></li>";
  $("#stat-top-artists").innerHTML    = fmt(s.top_artists);
  $("#stat-top-categories").innerHTML = fmt(s.top_categories);
  $("#stat-issue-artists").innerHTML  = fmt(s.top_issue_artists);
}

async function loadImages() {
  if (!state.character) return;
  const url = `/api/images?character=${encodeURIComponent(state.character)}`
            + `&view=${state.view}&page=${state.page}&per_page=${state.perPage}`
            + `&filter=${state.filter}&batch=${state.batch}`
            + `&artist=${encodeURIComponent(state.artist)}`
            + `&q=${encodeURIComponent(state.search)}`;
  const data = await api(url);
  state.total = data.total;
  state.pages = data.pages;
  renderGrid(data.images);
  renderPagination();
  updateViewLabel();
}

function updateViewLabel() {
  const labels = {
    output:    "📥 New",
    liked:     "❤️ Liked",
    bookmarks: "🔖 Bookmarks",
    archive:   "🗄️ Archive",
  };
  const hints  = {
    output:    "Vote on images here. Positive votes → Liked. Disliked/unvoted → Archive when you click Organize.",
    liked:     "Your liked images. 👎 any image to move it to Archive.",
    bookmarks: "Saved for reference / remix. Bookmarks don't get upscaled, don't move on vote — they just stay findable.",
    archive:   "All archived images. ❤️/👍 any image to rescue it back to Liked.",
  };
  $("#view-label").innerHTML =
    `<span class="view-name">${labels[state.view]}</span>` +
    `<span class="view-hint">${hints[state.view]}</span>` +
    `<span class="view-count">${state.total} image${state.total !== 1 ? "s" : ""}</span>`;
}

// Strip A1111-style emphasis weighting from a tag for matching purposes:
//   "(foot focus:1.2)" -> "foot focus"
//   "[de-emphasized]"  -> "de-emphasized"
function _stripEmphasis(tag) {
  let t = tag.trim();
  // (foo:1.3) or (foo)
  const m = t.match(/^\(\s*(.+?)\s*(?::[\d.]+)?\)$/);
  if (m) t = m[1];
  // [foo]
  const b = t.match(/^\[\s*(.+?)\s*\]$/);
  if (b) t = b[1];
  return t.trim();
}

function extractSceneTags(prompt) {
  if (!prompt) return [];
  // Per-character noise: trigger_word, character_tags, AND every outfit
  // bundle's tags (so "white kimono, red hakama" don't preview when the prompt
  // used {outfit}, since they were auto-injected).
  const charNoise = new Set();
  if (_charInfo) {
    if (_charInfo.trigger_word) charNoise.add(_charInfo.trigger_word.toLowerCase());
    const splitTags = s => s.split(",").map(t => _stripEmphasis(t).toLowerCase()).filter(Boolean);
    if (_charInfo.character_tags) splitTags(_charInfo.character_tags).forEach(t => charNoise.add(t));
    if (_charInfo.outfits && typeof _charInfo.outfits === "object") {
      for (const tags of Object.values(_charInfo.outfits)) {
        if (typeof tags === "string") splitTags(tags).forEach(t => charNoise.add(t));
      }
    }
  }
  return prompt.split(",").map(s => s.trim()).filter(Boolean)
    .filter(p => {
      const lo = _stripEmphasis(p).toLowerCase();
      return !p.startsWith("artist:")
          && !NOISY_TAGS.has(lo)
          && !charNoise.has(lo);
    })
    .slice(0, 8);
}

function renderGrid(images) {
  const grid = $("#grid");
  grid.innerHTML = "";
  const tpl = $("#card-tpl");
  if (!images.length) {
    grid.innerHTML = `<p class="empty-msg">No images in ${state.view} matching the current filter.</p>`;
    return;
  }
  images.forEach(img => {
    const node = tpl.content.cloneNode(true);
    const card = node.querySelector(".card");
    card.dataset.stem     = img.stem;
    card.dataset.location = img.location || state.view;
    if (img.votes?.super_like)    card.classList.add("has-super-like");
    if (img.votes?.love)          card.classList.add("has-love");
    if (img.votes?.anatomy_issue) card.classList.add("has-issue");
    if (img.votes?.dislike)       card.classList.add("has-dislike");

    const im = card.querySelector(".thumb");
    // Default to upscaled version when available and toggle is on
    const useUpscaled = state.showUpscaled && img.upscaled_filename;
    im.src = `/img/${state.character}/${useUpscaled ? img.upscaled_filename : img.filename}`;
    im.dataset.originalFilename = img.filename;
    im.dataset.upscaledFilename = img.upscaled_filename || "";
    im.alt = img.label;
    if (img.upscaled_filename) card.classList.add("has-upscaled");

    card.querySelector(".card-id").textContent = img.id ? `#${String(img.id).padStart(3, "0")}` : "";
    card.querySelector(".label").textContent   = img.label;

    const badge = card.querySelector(".location-badge");
    if (img.votes?.bookmark) {
      badge.textContent = "🔖";
      badge.classList.add("badge-bookmark");
    } else if (state.view === "archive") badge.textContent = "🗄️";
    else if (state.view === "liked" && img.upscaled_filename) {
      badge.textContent = "✨ 2K";
      badge.classList.add("badge-upscaled");
    }
    if (img.votes?.bookmark) card.classList.add("has-bookmark");

    // Upscale status icon + Open Original button
    const upscaleIcon = card.querySelector(".upscale-status");
    const openOrig    = card.querySelector(".open-original-btn");
    if (img.upscaled_filename) {
      upscaleIcon.classList.add("active");
      upscaleIcon.title = "✨ 2K upscale available — click 🔍 1K to see the original";
      openOrig.disabled = false;
    } else {
      upscaleIcon.classList.remove("active");
      upscaleIcon.title = "No 2K upscale yet";
      openOrig.disabled = true;
      openOrig.title    = "No 2K upscale yet — main thumbnail is already the original";
    }
    openOrig.addEventListener("click", e => {
      e.stopPropagation();
      // Always opens the unupscaled original
      openLightbox(`/img/${state.character}/${img.filename}`);
    });

    // Remix button — open Add prompt modal pre-filled with this image's tags.
    // Seed is intentionally NOT copied: a remix is a fresh roll with the same prompt.
    const remixBtn = card.querySelector(".remix-btn");
    remixBtn.addEventListener("click", e => {
      e.stopPropagation();
      const w = im.naturalWidth  || 1024;
      const h = im.naturalHeight || 1024;
      addPromptModalOpen({
        label:  (img.label || "remix") + "-remix",
        prompt: stripUserPrompt(img.prompt),
        width:  w,
        height: h,
      });
    });

    const at = card.querySelector(".artist-tags");
    (img.artists || []).forEach(a => {
      const span = document.createElement("span");
      span.className = "tag"; span.textContent = `🎨 ${a.trim()}`;
      at.appendChild(span);
    });

    const st = card.querySelector(".scene-tags");
    extractSceneTags(img.prompt).forEach(t => {
      const span = document.createElement("span");
      span.className = "tag"; span.textContent = t;
      st.appendChild(span);
    });

    // Wire up every vote button (primary row + menu rows). data-vote drives behavior.
    card.querySelectorAll("button[data-vote]").forEach(btn => {
      const v = btn.dataset.vote;
      if (img.votes?.[v]) btn.classList.add("active");
      btn.addEventListener("click", e => {
        e.stopPropagation();
        toggleVote(card, btn, v);
      });
    });

    // Hamburger menu — opens as a floating popover anchored under the ⋮ button
    const menuBtn = card.querySelector(".card-menu-btn");
    const menu    = card.querySelector(".card-menu");
    if (menuBtn && menu) {
      menuBtn.addEventListener("click", e => {
        e.stopPropagation();
        const willOpen = menu.classList.contains("hidden");
        // Close any other open menus first
        $$(".card-menu").forEach(m => m.classList.add("hidden"));
        $$(".card-menu-btn.active").forEach(b => b.classList.remove("active"));
        $$(".card.menu-open").forEach(c => c.classList.remove("menu-open"));
        if (willOpen) {
          // Position the menu just below the ⋮ button, snapped to the card's right edge
          const btnRect  = menuBtn.getBoundingClientRect();
          const cardRect = card.getBoundingClientRect();
          menu.style.top = `${btnRect.bottom - cardRect.top + 4}px`;
          menu.classList.remove("hidden");
          menuBtn.classList.add("active");
          card.classList.add("menu-open");   // releases overflow: hidden so the popover can spill
        }
      });
      // Stop clicks INSIDE the menu from closing it
      menu.addEventListener("click", e => e.stopPropagation());
    }

    // Upscale Now button
    const upscaleNowBtn = card.querySelector(".upscale-now-btn");
    if (upscaleNowBtn) {
      // Disable if a 2K upscale already exists (same logic as the badge)
      const has2K = img.upscaled_filename && img.upscaled_filename.endsWith("_2k.png");
      if (has2K) {
        upscaleNowBtn.disabled = true;
        upscaleNowBtn.textContent = "✅ Already SDXL-upscaled";
      }
      upscaleNowBtn.addEventListener("click", async e => {
        e.stopPropagation();
        upscaleNowBtn.disabled = true;
        upscaleNowBtn.textContent = "⏳ Upscaling…";
        try {
          const r = await postJSON("/api/upscale-one", {
            character: state.character, stem: img.stem, scale: state.upscaleScale,
          });
          if (r.ok) {
            toast(`🔼 Upscaling ${img.stem} — see Generation page for progress`);
          } else {
            toast("❌ " + r.err);
            upscaleNowBtn.disabled = false;
            upscaleNowBtn.textContent = "🔼 Upscale now";
          }
        } catch (err) {
          toast("❌ " + err.message);
          upscaleNowBtn.disabled = false;
          upscaleNowBtn.textContent = "🔼 Upscale now";
        }
      });
    }

    const ta = card.querySelector(".comment");
    ta.value = img.comment || "";
    let saveTimer;
    const save = () => saveComment(img.stem, ta.value);
    ta.addEventListener("blur", save);
    ta.addEventListener("input", () => { clearTimeout(saveTimer); saveTimer = setTimeout(save, 1500); });

    card.querySelector(".prompt-box").textContent = img.prompt || "";

    card.querySelector(".thumb-wrap").addEventListener("click", e => {
      if (e.target.classList.contains("card-id") || e.target.classList.contains("location-badge")) return;
      // Lightbox always shows the highest-res version available
      const best = img.upscaled_filename
        ? `/img/${state.character}/${img.upscaled_filename}`
        : `/img/${state.character}/${img.filename}`;
      openLightbox(best);
    });

    grid.appendChild(node);
  });
}

function renderPagination() {
  const nav = $("#pagination");
  nav.innerHTML = "";
  if (state.pages <= 1 && state.total === 0) {
    nav.innerHTML = `<span class="info">No results</span>`; return;
  }
  const mk = (label, page, opts = {}) => {
    const b = document.createElement("button");
    b.textContent = label;
    if (opts.current)  b.className = "current";
    if (opts.disabled) b.disabled  = true;
    if (!opts.disabled) b.addEventListener("click", () => {
      state.page = page; loadImages();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    return b;
  };
  nav.appendChild(mk("‹ Prev", state.page - 1, { disabled: state.page === 1 }));
  // Show ALL page numbers so any page can be jumped to directly
  for (let p = 1; p <= state.pages; p++) {
    nav.appendChild(mk(String(p), p, { current: p === state.page }));
  }
  nav.appendChild(mk("Next ›", state.page + 1, { disabled: state.page >= state.pages }));
  const info = document.createElement("span");
  info.className = "info";
  info.textContent = `${state.total} images · page ${state.page} / ${state.pages}`;
  nav.appendChild(info);
}

async function toggleVote(card, btn, voteType) {
  const stem  = card.dataset.stem;
  const value = !btn.classList.contains("active");
  btn.classList.toggle("active", value);
  if (voteType === "super_like")    card.classList.toggle("has-super-like", value);
  if (voteType === "love")          card.classList.toggle("has-love",    value);
  if (voteType === "anatomy_issue") card.classList.toggle("has-issue",   value);
  if (voteType === "dislike")       card.classList.toggle("has-dislike", value);

  try {
    const json = await postJSON("/api/vote", {
      character: state.character, stem, vote_type: voteType, value, view: state.view,
    });
    if (json.moved) {
      const dest = json.moved === "liked" ? "❤️ Liked" : "🗄️ Archive";
      toast(`Moved to ${dest}`);
      card.classList.add("card-leaving");
      setTimeout(() => {
        card.remove();
        state.total = Math.max(0, state.total - 1);
        updateViewLabel();
        loadArtists();
        const remaining = $$("#grid .card").length;
        if (remaining === 0 && state.page > 1) { state.page--; loadImages(); }
      }, 350);
    }
    loadStats();
  } catch (e) { console.error("vote failed", e); }
}

async function saveComment(stem, text) {
  try {
    await postJSON("/api/comment", { character: state.character, stem, comment: text });
  } catch (e) { console.error("comment save failed", e); }
}

// ── Review: tools ─────────────────────────────────────────────────────────
async function organizeOutput() {
  const btn = $("#organize");
  btn.disabled = true; btn.textContent = "⏳ Organizing…";
  try {
    const r = await postJSON("/api/organize", { character: state.character });
    if (r.ok) {
      toast(`✅ ${r.moved_liked} → Liked, ${r.moved_archive} → Archive, ${r.skipped} skipped`);
      await loadArtists();
      await loadImages();
      await loadStats();
      // Refresh _charInfo so the next Add-prompt modal shows updated popular tags
      // computed from the newly-organized liked/ folder.
      await loadCharacterInfo();
    } else { toast("❌ Organize failed"); }
  } catch (e) { toast("❌ Organize failed"); }
  finally { btn.disabled = false; btn.textContent = "📦 Organize"; }
}
async function startUpscale() {
  // Trigger upscale, then jump to Generation page so the user sees the unified banner
  const r = await postJSON("/api/upscale", { character: state.character, scale: state.upscaleScale });
  if (r.ok) {
    toast(`🔼 Upscale started @ ${state.upscaleScale}× — see Generation page`);
    switchPage("generation");
  } else {
    toast("❌ " + r.err);
  }
}
// ── Tool widget (upscale live progress) ──────────────────────────────────
let _toolPoll = null;
let _toolPollName = null;
function startToolPoll(toolName, icon, prettyName) {
  $("#tool-widget-icon").textContent = icon;
  $("#tool-widget-name").textContent = prettyName;
  $("#tool-widget").classList.remove("hidden");
  _toolPollName = toolName;
  pollToolStatus();
  if (_toolPoll) clearInterval(_toolPoll);
  _toolPoll = setInterval(pollToolStatus, 1500);
}
async function pollToolStatus() {
  if (!_toolPollName) return;
  try {
    const s = await api(`/api/tool/status?tool=${encodeURIComponent(_toolPollName)}`);
    if (s.state === "running") {
      const pct = s.total ? Math.round(100 * s.current_index / s.total) : 0;
      $("#tool-widget-progress").style.width = pct + "%";
      $("#tool-widget-status").textContent = s.total ? `${s.current_index}/${s.total}` : "starting…";
      $("#tool-widget-current").textContent = s.current_label
        ? `${s.current_label} (${s.last_dur_s.toFixed(1)}s)`
        : "(loading model…)";
    } else if (s.state === "completed" || s.state === "error") {
      const pct = s.total ? Math.round(100 * s.current_index / s.total) : 100;
      $("#tool-widget-progress").style.width = pct + "%";
      $("#tool-widget-status").textContent = s.state === "completed" ? "✅ done" : `❌ exit ${s.exit_code}`;
      $("#tool-widget-current").textContent = `${s.current_index}/${s.total} processed`;
      // Refresh review images / artists since liked/ folder changed
      if (state.page_active === "review") {
        loadArtists(); loadImages();
      }
      // Auto-hide after a few seconds
      setTimeout(() => {
        $("#tool-widget").classList.add("hidden");
      }, 5000);
      clearInterval(_toolPoll); _toolPoll = null; _toolPollName = null;
    } else {
      // idle = nothing running
      $("#tool-widget").classList.add("hidden");
      clearInterval(_toolPoll); _toolPoll = null; _toolPollName = null;
    }
  } catch (e) { console.warn("tool poll failed", e); }
}
async function stopTool() {
  if (!_toolPollName) return;
  if (!confirm(`Stop the running ${_toolPollName}?`)) return;
  const r = await postJSON("/api/tool/stop", { tool: _toolPollName });
  if (r.ok) toast("Stop signal sent");
  else toast("❌ " + r.err);
}
// On page load, check if anything is already running and resume polling
async function resumeToolPollIfRunning() {
  for (const [tool, icon, name] of [["upscale", "🔼", "Upscale"]]) {
    try {
      const s = await api(`/api/tool/status?tool=${tool}`);
      if (s.state === "running") {
        startToolPoll(tool, icon, name);
        return;
      }
    } catch (e) {}
  }
}

// ── Activity ──────────────────────────────────────────────────────────────
async function loadActivity() {
  const event = $("#activity-filter").value;
  const url = `/api/activity?character=${encodeURIComponent(state.character || "")}&limit=200`
            + (event ? `&event=${event}` : "");
  const { events } = await api(url);
  const ul = $("#activity-list");
  ul.innerHTML = "";
  if (!events.length) { ul.innerHTML = '<li class="muted">No events yet</li>'; return; }
  events.slice().reverse().forEach(ev => {
    const li = document.createElement("li");
    const ts = new Date(ev.ts).toLocaleString();
    const fields = Object.entries(ev)
      .filter(([k]) => !["ts", "event", "character"].includes(k))
      .map(([k, v]) => `<span class="ev-field"><b>${k}</b>=${escapeHTML(String(v))}</span>`)
      .join(" ");
    li.innerHTML = `<span class="ev-ts">${ts}</span> <span class="ev-name">${ev.event}</span> ${fields}`;
    ul.appendChild(li);
  });
}

// ── Lightbox ──────────────────────────────────────────────────────────────
function openLightbox(src) {
  $("#lightbox-img").src = src;
  $("#lightbox").classList.remove("hidden");
}
$("#lightbox").addEventListener("click", e => {
  if (e.target.id !== "lightbox-img") $("#lightbox").classList.add("hidden");
});

// ── Wire-up ───────────────────────────────────────────────────────────────
$$(".page-btn").forEach(b => b.addEventListener("click", () => switchPage(b.dataset.page)));
// Show Organize only on the New tab; Upscale liked only on the Liked tab.
function updateTabActionButtons() {
  $("#organize").classList.toggle("hidden", state.view !== "output");
  $("#upscale-btn").classList.toggle("hidden", state.view !== "liked");
}
$$(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    state.view = tab.dataset.view; state.page = 1; state.filter = "all"; state.artist = "all";
    $("#filter").value = "all";
    updateTabActionButtons();
    Promise.all([loadBatches(), loadArtists()]).then(loadImages);
  });
});

$("#character").addEventListener("change", e => {
  state.character = e.target.value;
  localStorage.setItem("character", state.character);
  switchPage(state.page_active);
});
$("#batch").addEventListener("change", e => { state.batch = e.target.value; state.page = 1; loadImages(); });
$("#filter").addEventListener("change", e => { state.filter = e.target.value; state.page = 1; loadImages(); });
$("#artist").addEventListener("change", e => { state.artist = e.target.value; state.page = 1; loadImages(); });
let _searchTimer;
$("#search").addEventListener("input", e => {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => {
    state.search = e.target.value.trim();
    state.page = 1;
    loadImages();
  }, 300);   // debounce: wait 300ms after typing stops
});
$("#search").addEventListener("keydown", e => {
  if (e.key === "Escape") { e.target.value = ""; state.search = ""; state.page = 1; loadImages(); }
});
$("#refresh").addEventListener("click", async () => {
  await fetch("/api/refresh"); loadBatches(); loadArtists(); loadImages(); loadStats();
});
$("#toggle-upscaled").addEventListener("click", () => {
  state.showUpscaled = !state.showUpscaled;
  localStorage.setItem("showUpscaled", state.showUpscaled);
  $("#toggle-upscaled").classList.toggle("active", state.showUpscaled);
  $("#toggle-upscaled").textContent = state.showUpscaled ? "✨ 2K" : "🖼️ Original";
  loadImages();
});
$("#organize").addEventListener("click", organizeOutput);
$("#upscale-btn").addEventListener("click", startUpscale);

// Two number inputs (one in the Generation banner, one in the Review toolbar)
// stay in sync with state.upscaleScale + localStorage. Anything reading
// state.upscaleScale at click time picks up the latest value.
function syncUpscaleScaleInputs() {
  document.querySelectorAll(".upscale-scale").forEach(el => {
    el.value = state.upscaleScale.toFixed(2).replace(/\.?0+$/, "");
  });
}
function applyUpscaleScale(raw) {
  let v = parseFloat(raw);
  if (!Number.isFinite(v)) v = 2.0;
  v = Math.max(1.0, Math.min(3.0, v));
  // Round to two decimals to keep persisted values clean
  v = Math.round(v * 100) / 100;
  state.upscaleScale = v;
  localStorage.setItem("upscaleScale", String(v));
  syncUpscaleScaleInputs();
}
document.querySelectorAll(".upscale-scale").forEach(el => {
  el.addEventListener("change", e => applyUpscaleScale(e.target.value));
});
syncUpscaleScaleInputs();

// Gear button next to each Upscale button toggles a settings popover.
// Click-outside or Esc closes any open popover.
document.querySelectorAll(".upscale-settings-btn").forEach(btn => {
  btn.addEventListener("click", e => {
    e.stopPropagation();
    const popover = btn.parentElement.querySelector(".upscale-settings-popover");
    if (!popover) return;
    const wasOpen = !popover.classList.contains("hidden");
    document.querySelectorAll(".upscale-settings-popover").forEach(p => p.classList.add("hidden"));
    if (!wasOpen) popover.classList.remove("hidden");
  });
});
document.addEventListener("click", e => {
  document.querySelectorAll(".upscale-settings-popover:not(.hidden)").forEach(p => {
    if (!p.contains(e.target) && !e.target.classList.contains("upscale-settings-btn")) {
      p.classList.add("hidden");
    }
  });
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    document.querySelectorAll(".upscale-settings-popover:not(.hidden)").forEach(p => p.classList.add("hidden"));
  }
});
// Initial visibility (default tab is New / output)
updateTabActionButtons();
$("#toggle-stats").addEventListener("click", () => {
  $("#stats").classList.toggle("hidden");
  if (!$("#stats").classList.contains("hidden")) loadStats();
});

// Generation
$("#run-start").addEventListener("click", startRun);
$("#run-upscale").addEventListener("click", startUpscaleFromBanner);
$("#run-train").addEventListener("click", startTraining);
$("#run-stop").addEventListener("click", stopRun);
$("#chain-after-upscale").addEventListener("change", async e => {
  const r = await postJSON("/api/run/chain-after-upscale", {
    character: state.character, enabled: e.target.checked,
  });
  if (r.ok) toast(r.chain_after_upscale ? "Generation will auto-start when upscale finishes" : "Auto-start cancelled");
});
$("#chain-after-training").addEventListener("change", async e => {
  const r = await postJSON("/api/training/chain-to-gen", {
    character: state.character, enabled: e.target.checked,
  });
  if (r.ok) toast(r.chain_after_training ? "Generation will auto-start when training finishes" : "Auto-start cancelled");
});
$("#queue-add").addEventListener("click", addPromptModalOpen);
$("#queue-shuffle").addEventListener("click", async () => {
  if (!confirm("Shuffle the entire queue? This randomizes the run order.")) return;
  const r = await postJSON("/api/queue/shuffle", { character: state.character });
  if (r.ok) {
    toast(`🔀 Shuffled ${r.shuffled} prompts`);
    loadQueue();
  } else {
    toast("❌ " + (r.err || "shuffle failed"));
  }
});
$("#queue-import").addEventListener("click", () => $("#modal-import").classList.remove("hidden"));
$("#queue-export").addEventListener("click", () => {
  window.location = `/api/queue/export?character=${encodeURIComponent(state.character)}`;
});
$("#queue-clear").addEventListener("click", clearQueue);
$("#add-cancel").addEventListener("click", () => {
  _editingLabel = null;
  $("#modal-add").classList.add("hidden");
});
$("#add-save").addEventListener("click", addPromptModalSave);
// Chip-button click → append tag (event delegation across all chip rows)
$("#modal-add").addEventListener("click", e => {
  const btn = e.target.closest(".chip-btn");
  if (btn && btn.dataset.tag) {
    e.preventDefault();
    appendTagToPrompt(btn.dataset.tag);
  }
});
$("#import-cancel").addEventListener("click", () => $("#modal-import").classList.add("hidden"));
$("#import-save").addEventListener("click", importYAMLModalSave);

// Activity
$("#activity-filter").addEventListener("change", loadActivity);
$("#activity-refresh").addEventListener("click", loadActivity);

// Tool widget
$("#tool-widget-stop").addEventListener("click", stopTool);

// Click anywhere outside an open card-menu closes all menus
document.addEventListener("click", () => {
  $$(".card-menu").forEach(m => m.classList.add("hidden"));
  $$(".card-menu-btn.active").forEach(b => b.classList.remove("active"));
  $$(".card.menu-open").forEach(c => c.classList.remove("menu-open"));
});

// ── Add character modal ─────────────────────────────────────────────────
function openAddCharacterModal() {
  $("#add-character-error").classList.add("hidden");
  $("#add-character-name").value = "";
  $("#modal-add-character").classList.remove("hidden");
  setTimeout(() => $("#add-character-name").focus(), 50);
}
function closeAddCharacterModal() {
  $("#modal-add-character").classList.add("hidden");
}
async function createCharacter() {
  const name = $("#add-character-name").value.trim();
  const errEl = $("#add-character-error");
  errEl.classList.add("hidden");
  if (!/^[a-z][a-z0-9_]{1,30}$/.test(name)) {
    errEl.textContent = "Name must be lowercase, start with a letter, "
                      + "and contain only a–z, 0–9, _ (1–31 chars).";
    errEl.classList.remove("hidden");
    return;
  }
  const r = await postJSON("/api/character/create", { name });
  if (!r.ok) {
    errEl.textContent = r.err || "Create failed";
    errEl.classList.remove("hidden");
    return;
  }
  toast(`✅ Created character "${name}"`);
  closeAddCharacterModal();
  // Reload the dropdown, switch to the new character so the user can immediately
  // start dropping training images / editing config from the active session.
  await loadCharacters();
  state.character = name;
  $("#character").value = name;
  localStorage.setItem("character", name);
  await loadCharacterInfo();
  await Promise.all([loadBatches(), loadArtists(), loadStats()]);
  await loadImages();
  await loadQueue();
}
$("#add-character").addEventListener("click", openAddCharacterModal);
$("#add-character-cancel").addEventListener("click", closeAddCharacterModal);
$("#add-character-create").addEventListener("click", createCharacter);
$("#add-character-name").addEventListener("keydown", e => {
  if (e.key === "Enter") createCharacter();
  else if (e.key === "Escape") closeAddCharacterModal();
});

// Bootstrap
(async () => {
  $("#toggle-upscaled").classList.toggle("active", state.showUpscaled);
  $("#toggle-upscaled").textContent = state.showUpscaled ? "✨ 2K" : "🖼️ Original";
  await loadCharacters();
  switchPage(state.page_active);
  resumeToolPollIfRunning();
  // Always poll the run banner once on load — picks up running upscale too
  pollRunStatus();
})();

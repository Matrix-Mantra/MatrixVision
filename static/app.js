/* Matrix Vision web app. Plain JavaScript, no build step. Same helpers and sign-in as Matrix. */

// ------------------------------------------------------------------ small helpers
const $ = (id) => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* unavailable */ } },
};

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return n;
}
// replaceChildren() would print "null" for sections that are not shown.
const render = (parent, ...kids) => parent.replaceChildren(...kids.flat().filter((k) => k != null && k !== false));
const srOnly = (text) => el("span", { class: "sr-only", text });
const newTab = () => srOnly(` ${t("newTab")}`);

const S = {
  lang: store.get("mv_lang") || "ne",
  cfg: null,
  user: null,
  getToken: async () => null,
  // The current scan lives only in memory: never saved in the browser or on the server.
  photoUrl: null,
  result: null,
  district: store.get("mv_district") || "",
};
const t = (k, ...a) => { const v = (window.I18N[S.lang] || window.I18N.ne)[k]; return typeof v === "function" ? v(...a) : v; };
const L = (obj) => (obj ? obj[S.lang] || obj.ne || obj.en || "" : "");
const hName = (h) => (S.lang === "ne" && h.name_ne ? h.name_ne : h.name);

function toast(msg) {
  const box = $("toast"); box.textContent = msg; box.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { box.hidden = true; }, 4500);
}

// ------------------------------------------------------------------ api
const SLOW = 120000;  // scanning calls two Meta models; give it time on slow networks

async function api(path, { method = "GET", body, form, auth = false, raw = false, timeout = 20000 } = {}) {
  const headers = {};
  if (auth) { const tok = await S.getToken(); if (tok) headers.Authorization = `Bearer ${tok}`; }
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  let res;
  try { res = await fetch(path, { method, headers, body: payload, signal: ctl.signal }); }
  catch (err) { throw new Error(err.name === "AbortError" ? t("slowNet") : t("netError")); }
  finally { clearTimeout(timer); }
  if (raw && res.ok) return res;
  let data = null; try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const e = new Error((data && typeof data.detail === "string" && data.detail) || t("netError"));
    e.status = res.status; e.data = data; throw e;
  }
  return data;
}

function errorText(e) {
  const code = e.data && e.data.code;
  if (code && t("errors")[code]) return t("errors")[code];
  if (e.status === 429) return t("errors").limit;
  if (e.status === 401) return t("errors").login;
  return e.message;
}

// ------------------------------------------------------------------ sign-in (same Firebase project as Matrix)
let firebaseAuth = null;
let afterLogin = null;

async function initAuth() {
  if (S.cfg.auth_mode === "firebase" && S.cfg.firebase && S.cfg.firebase.apiKey) {
    const V = "10.12.2";
    const appMod = await import(`https://www.gstatic.com/firebasejs/${V}/firebase-app.js`);
    const authMod = await import(`https://www.gstatic.com/firebasejs/${V}/firebase-auth.js`);
    const auth = authMod.getAuth(appMod.initializeApp(S.cfg.firebase));
    firebaseAuth = { auth, ...authMod };
    S.getToken = async () => (auth.currentUser ? auth.currentUser.getIdToken() : null);
    await new Promise((resolve) => {
      authMod.onAuthStateChanged(auth, (u) => {
        S.user = u ? { name: u.displayName || (u.email || "").split("@")[0] } : null;
        renderHeader(); resolve();
        if (u && afterLogin) { const f = afterLogin; afterLogin = null; f(); }
      });
    });
    authMod.getRedirectResult(auth).catch(() => {});
  } else {
    const name = store.get("mv_dev_name");
    S.user = name ? { name } : null;
    S.getToken = async () => (S.user ? `dev:${S.user.name}` : null);
  }
}

function openLogin() {
  $("loginTitle").textContent = t("loginTitle");
  $("loginWhy").textContent = t("loginWhy");
  $("loginError").hidden = true;
  const fb = S.cfg.auth_mode === "firebase";
  $("googleBtn").hidden = !fb; $("devLogin").hidden = fb;
  $("googleLabel").textContent = t("google");
  $("devNameLabel").textContent = t("devName"); $("devGo").textContent = t("devGo"); $("devNote").textContent = t("devNote");
  $("loginCancel").textContent = t("cancel");
  $("loginSheet").showModal();
  if (!fb) $("devName").focus();
}

function requireLogin(then) {
  if (S.user) { then(); return; }
  afterLogin = then; openLogin();
}

async function googleLogin() {
  const { auth, GoogleAuthProvider, signInWithPopup, signInWithRedirect } = firebaseAuth;
  const provider = new GoogleAuthProvider();
  try { await signInWithPopup(auth, provider); $("loginSheet").close(); }
  catch (e) {
    if (e && (e.code === "auth/popup-blocked" || e.code === "auth/operation-not-supported-in-this-environment")) {
      await signInWithRedirect(auth, provider);
    } else if (!(e && e.code === "auth/popup-closed-by-user")) {
      console.error("Google sign-in failed", e);
      $("loginError").textContent = t("loginFailed"); $("loginError").hidden = false;
    }
  }
}

function devLogin() {
  const name = $("devName").value.trim().replace(/[^\p{L}\p{N} _.-]/gu, "").slice(0, 40);
  if (!name) { $("devName").focus(); return; }
  store.set("mv_dev_name", name); S.user = { name };
  $("loginSheet").close(); renderHeader();
  if (afterLogin) { const f = afterLogin; afterLogin = null; f(); }
}

async function logout() {
  if (firebaseAuth) await firebaseAuth.signOut(firebaseAuth.auth);
  store.set("mv_dev_name", null); S.user = null; renderHeader();
}

function renderHeader() {
  document.documentElement.lang = S.lang;
  $("langBtn").textContent = t("other");
  $("loginBtn").textContent = t("login"); $("logoutBtn").textContent = t("logout");
  $("loginBtn").hidden = !!S.user; $("logoutBtn").hidden = !S.user;
}

// ------------------------------------------------------------------ photo: shrink on the phone before upload

const MAX_SIDE = 2000;

async function shrink(file) {
  // HEIC can't be decoded by most browsers: send it as is and let the server convert it.
  if (!window.createImageBitmap) return file;
  let bmp;
  try { bmp = await createImageBitmap(file, { imageOrientation: "from-image" }); } catch { return file; }
  const scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
  if (scale === 1 && file.size < 2.5e6 && file.type === "image/jpeg") { bmp.close(); return file; }
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  bmp.close();
  const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.85));
  return blob ? new File([blob], "document.jpg", { type: "image/jpeg" }) : file;
}

function setPhoto(file) {
  if (S.photoUrl) URL.revokeObjectURL(S.photoUrl);
  S.photoFile = file;
  S.photoUrl = URL.createObjectURL(file);
}

// ------------------------------------------------------------------ home: scan a document

function viewHome() {
  const view = $("view");
  const camera = el("input", { type: "file", accept: "image/*,.heic,.heif", capture: "environment", class: "sr-only", id: "cameraInput" });
  const gallery = el("input", { type: "file", accept: "image/jpeg,image/png,image/heic,image/heif,.heic,.heif", class: "sr-only", id: "galleryInput" });
  const preview = el("div", { class: "preview", hidden: true });
  const note = el("textarea", { class: "input", rows: 2, maxlength: 500, placeholder: t("notePh"), "aria-label": t("notePh") });
  const districtSel = el("select", { class: "input", id: "districtSel" },
    el("option", { value: "", text: t("anyDistrict") }),
    (S.cfg.districts || []).map((d) => el("option", { value: d, text: d, selected: d === S.district })));
  const scanBtn = el("button", { class: "primary-btn wide", type: "button", disabled: true, text: t("scan") });
  const status = el("p", { class: "error", role: "alert", hidden: true });

  async function picked(input) {
    const file = input.files && input.files[0];
    input.value = "";
    if (!file) return;
    setPhoto(await shrink(file));
    preview.replaceChildren(el("img", { src: S.photoUrl, alt: "" }),
      el("button", { class: "text-btn", type: "button", text: t("retake"), onclick: () => camera.click() }));
    preview.hidden = false; scanBtn.disabled = false; status.hidden = true;
    scanBtn.focus();
  }
  camera.addEventListener("change", () => picked(camera));
  gallery.addEventListener("change", () => picked(gallery));
  districtSel.addEventListener("change", () => { S.district = districtSel.value; store.set("mv_district", S.district || null); });
  scanBtn.addEventListener("click", () => requireLogin(() => runScan(note.value.trim(), status)));

  render(view,
    el("section", { class: "hero" },
      el("h1", { text: t("heroTitle") }),
      el("p", { class: "muted", text: t("heroSub") }),
      el("ul", { class: "chips" }, t("kinds").map((k) => el("li", { text: k })))),
    el("div", { class: "pick" },
      el("label", { class: "primary-btn wide big", for: "cameraInput" }, cameraIcon(), t("takePhoto")),
      el("label", { class: "secondary-btn wide", for: "galleryInput", text: t("fromGallery") }),
      camera, gallery),
    el("p", { class: "muted small", text: t("tips") }),
    preview,
    el("div", { class: "fields" },
      note,
      el("label", { class: "small muted", for: "districtSel", text: t("district") }), districtSel),
    scanBtn, status,
    el("p", { class: "muted small privacy", text: t("privacy") }),
    disclaimerBox(S.cfg.disclaimer),
    el("p", { class: "muted small center" }, el("a", { href: S.cfg.matrix_url, target: "_blank", rel: "noopener", text: t("matrixLink") }), newTab(),
      " · ", t("poweredBy")),
  );
  if (S.photoUrl) {
    preview.replaceChildren(el("img", { src: S.photoUrl, alt: "" }));
    preview.hidden = false; scanBtn.disabled = false;
  }
}

function cameraIcon() {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", "M9 3 7.2 5H4a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-3.2L15 3H9Zm3 5a5 5 0 1 1 0 10 5 5 0 0 1 0-10Zm0 2a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z");
  s.append(p); return s;
}

function disclaimerBox(d) {
  if (!d) return null;
  return el("aside", { class: "disclaimer small" }, el("p", { text: d.ne }), el("p", { text: d.en, lang: "en" }));
}

function emergencyBox(safety) {
  if (!safety || !safety.is_emergency) return null;
  return el("section", { class: "emergency", role: "alert" },
    el("h2", { text: t("emergencyTitle") }),
    el("a", { class: "call-btn", href: "tel:102" }, t("call102")),
    el("ul", {}, safety.flags.map((f) => el("li", {}, el("strong", { text: f[`label_${S.lang}`] }), " ", f[`action_${S.lang}`]))));
}

async function runScan(note, status) {
  const view = $("view");
  const stepText = el("p", { class: "step", "aria-live": "polite", text: t("steps")[0] });
  render(view, el("section", { class: "working" },
    el("div", { class: "scan-photo" }, el("img", { src: S.photoUrl, alt: "" }), el("div", { class: "scanline", "aria-hidden": "true" })),
    stepText));
  let i = 0;
  const tick = setInterval(() => { i = Math.min(i + 1, t("steps").length - 1); stepText.textContent = t("steps")[i]; }, 4500);
  const form = new FormData();
  form.append("image", S.photoFile, S.photoFile.name || "document.jpg");
  form.append("note", note); form.append("lang", S.lang);
  if (S.district) form.append("district", S.district);
  try {
    S.result = await api("/api/vision", { method: "POST", form, auth: true, timeout: SLOW });
    S.answers = [];
    location.hash = "#/result";
    if (location.hash === "#/result") route();
  } catch (e) {
    viewHome();
    const box = $("view");
    // The safety check runs even when reading failed: show "Call 102" first.
    const em = emergencyBox(e.data && e.data.safety);
    if (em) box.prepend(em);
    const err = box.querySelector(".error");
    err.textContent = errorText(e); err.hidden = false;
    if (e.status === 401) { S.user = null; renderHeader(); }
  } finally { clearInterval(tick); }
}

// ------------------------------------------------------------------ result

function flagChip(flag) {
  return el("span", { class: `chip flag-${flag}`, text: t("flag")[flag] || flag });
}

function photoWithRegions(regions) {
  const wrap = el("div", { class: "photo", id: "photo" }, el("img", { src: S.photoUrl, alt: "" }));
  for (const r of regions || []) {
    const [x1, y1, x2, y2] = r.box;
    wrap.append(el("div", { class: `region kind-${r.kind}`, id: `reg-${r.id}`, "data-label": r.id,
      style: `left:${x1 * 100}%;top:${y1 * 100}%;width:${(x2 - x1) * 100}%;height:${(y2 - y1) * 100}%` }));
  }
  return wrap;
}

function highlight(ids) {
  document.querySelectorAll(".region.on").forEach((n) => n.classList.remove("on"));
  const nodes = (ids || []).map((id) => $(`reg-${id}`)).filter(Boolean);
  nodes.forEach((n) => n.classList.add("on"));
  if (nodes.length) $("photo").scrollIntoView({ behavior: "smooth", block: "center" });
}

function showBtn(regionId) {
  if (!regionId || !$(`reg-${regionId}`)) return null;
  return el("button", { class: "text-btn small", type: "button", text: t("showOnPhoto"), onclick: () => highlight([regionId]) });
}

function itemRow(i) {
  return el("li", { class: `item ${["high", "low", "abnormal"].includes(i.flag) ? "is-abnormal" : ""}` },
    el("div", { class: "item-head" },
      el("strong", { text: i.name }), flagChip(i.flag)),
    el("div", { class: "item-value" },
      el("span", { class: "value", text: `${i.value} ${i.unit || ""}`.trim() }),
      i.reference_range ? el("span", { class: "muted small", text: ` · ${t("range")}: ${i.reference_range}` }) : null,
      i.flag_source === "range" ? el("span", { class: "muted small", text: ` (${t("flagByRange")})` }) : null),
    el("p", { text: i[`explanation_${S.lang}`] }),
    showBtn(i.region_id));
}

function hospitalCard(h) {
  return el("li", { class: "hospital" },
    el("strong", { text: hName(h) }),
    el("span", { class: "muted small", text: [h.city, h.district].filter(Boolean).join(", ") }),
    el("div", { class: "badges small" },
      h.emergency_24h ? el("span", { class: "chip ok", text: t("er24") }) : null,
      h.health_insurance ? el("span", { class: "chip", text: t("insurance") }) : null,
      h.verified ? null : el("span", { class: "chip muted-chip", text: t("notVerified") })),
    el("div", { class: "row" },
      el("a", { class: "secondary-btn", href: h.matrix_url, target: "_blank", rel: "noopener" }, t("openInMatrix"), newTab()),
      h.directions_url ? el("a", { class: "text-btn", href: h.directions_url, target: "_blank", rel: "noopener" }, t("directions"), newTab()) : null));
}

function hospitalsBlock(title, found) {
  if (!found) return null;
  const list = found.hospitals || [];
  return el("section", { class: "card" },
    el("h2", { text: title }),
    found.scope === "national" && found.district ? el("p", { class: "muted small", text: t("nationalScope") }) : null,
    list.length ? el("ul", { class: "hospitals" }, list.map(hospitalCard))
      : el("p", {}, t("noHospitals"), " ", el("a", { href: S.cfg.matrix_url, target: "_blank", rel: "noopener", text: "Matrix" }), newTab()));
}

// Read aloud with the phone's own voices (Meta has no text-to-speech): Nepali, else Hindi (same script).
function pickVoice() {
  const voices = (window.speechSynthesis && speechSynthesis.getVoices()) || [];
  const want = S.lang === "ne" ? ["ne", "hi"] : ["en"];
  for (const w of want) {
    const v = voices.find((x) => x.lang && x.lang.toLowerCase().startsWith(w));
    if (v) return v;
  }
  return null;
}

function speakText(text, btn) {
  if (!window.speechSynthesis) return;
  if (speechSynthesis.speaking) { speechSynthesis.cancel(); btn.textContent = t("listen"); return; }
  const voice = pickVoice();
  const u = new SpeechSynthesisUtterance(text);
  if (voice) { u.voice = voice; u.lang = voice.lang; } else u.lang = S.lang === "ne" ? "ne-NP" : "en-US";
  u.rate = 0.92;
  u.onend = () => { btn.textContent = t("listen"); };
  btn.textContent = t("stopListen");
  speechSynthesis.speak(u);
}

function listenBtn(getText) {
  if (!window.speechSynthesis) return null;
  const btn = el("button", { class: "secondary-btn small-btn", type: "button", text: t("listen") });
  btn.addEventListener("click", () => speakText(getText(), btn));
  const update = () => { btn.hidden = !pickVoice(); };
  update(); speechSynthesis.addEventListener("voiceschanged", update);
  return btn;
}

function viewResult() {
  const r = S.result;
  if (!r) { location.hash = "#/"; return; }
  const abnormal = r.items.filter((i) => ["high", "low", "abnormal"].includes(i.flag));
  const items = [...abnormal, ...r.items.filter((i) => !abnormal.includes(i))];
  const summary = L(r.summary);
  const answers = el("div", { class: "answers", "aria-live": "polite" });

  render($("view"),
    emergencyBox(r.safety),
    photoWithRegions(r.regions),
    el("section", { class: "card" },
      el("div", { class: "card-head" }, el("h2", { text: t("summary") }), listenBtn(() => summary)),
      el("p", { text: summary }),
      r.items.length ? el("p", { class: abnormal.length ? "warn" : "ok-text",
        text: abnormal.length ? t("abnormalFirst", abnormal.length) : t("allNormal") }) : null),
    r.items.length ? el("section", { class: "card" }, el("h2", { text: t("results") }), el("ul", { class: "items" }, items.map(itemRow))) : null,
    r.medicines.length ? el("section", { class: "card" }, el("h2", { text: t("medicines") }),
      el("ul", { class: "items" }, r.medicines.map((m) => el("li", { class: "item" },
        el("strong", { text: m.name }),
        el("div", { class: "med-how", text: [m.strength, m.dose, m.frequency, m.timing, m.duration].filter(Boolean).join(" · ") }),
        el("p", { text: m[`explanation_${S.lang}`] }), showBtn(m.region_id))))) : null,
    r.findings.length ? el("section", { class: "card" }, el("h2", { text: t("findings") }),
      el("ul", { class: "items" }, r.findings.map((f) => el("li", { class: "item" },
        el("strong", { text: f.text }), el("p", { text: f[`explanation_${S.lang}`] }), showBtn(f.region_id))))) : null,
    r.unreadable_parts.length ? el("section", { class: "card" }, el("h2", { text: t("unreadable") }),
      el("ul", {}, r.unreadable_parts.map((p) => el("li", { text: p })))) : null,
    el("section", { class: "card" }, el("h2", { text: t("deptTitle") }),
      el("p", {}, el("strong", { text: r.department[S.lang] || r.department.en }), " — ", L(r.department.reason))),
    hospitalsBlock(t("emergencyHospitals"), r.emergency_hospitals),
    hospitalsBlock(t("hospitalsTitle"), r.hospitals),
    askBlock(answers),
    L(r.questions_for_doctor).length ? el("section", { class: "card" }, el("h2", { text: t("doctorQs") }),
      el("ul", {}, L(r.questions_for_doctor).map((q) => el("li", { text: q })))) : null,
    el("div", { class: "row actions" },
      el("button", { class: "primary-btn", type: "button", text: t("pdf"), onclick: (e) => downloadPdf(e.currentTarget) }),
      el("a", { class: "secondary-btn", href: "#/", text: t("newScan"), onclick: () => { S.result = null; } })),
    disclaimerBox(r.disclaimer),
  );
  for (const a of S.answers || []) answers.append(answerNode(a));
}

// ------------------------------------------------------------------ follow-up questions

function docPayload() {
  const r = S.result;
  return { document_type: r.document_type, items: r.items, medicines: r.medicines, findings: r.findings, summary: r.summary,
    department: { id: r.department.id, ne: r.department.ne, en: r.department.en, reason: r.department.reason },
    context: r.context, questions_for_doctor: r.questions_for_doctor, regions: r.regions };
}

function answerNode(a) {
  return el("div", { class: "answer" },
    el("p", { class: "muted small" }, a.spoken ? `${t("weHeard")}: ` : "", el("em", { text: a.spoken ? a.understood || a.question : a.question })),
    emergencyBox(a.safety),
    el("p", { text: L(a.answer) }),
    a.region_ids && a.region_ids.length ? el("button", { class: "text-btn small", type: "button", text: t("showOnPhoto"),
      onclick: () => highlight(a.region_ids) }) : null);
}

async function ask(question, spoken, answers, status) {
  status.hidden = true;
  const pending = el("p", { class: "muted", text: t("understanding") });
  answers.prepend(pending);
  try {
    const res = await api("/api/vision/ask", { method: "POST", auth: true, timeout: SLOW,
      body: { question, spoken, lang: S.lang, district: S.district || null, document: docPayload() } });
    const a = { question, spoken, understood: res.question_understood, answer: res.answer, region_ids: res.region_ids, safety: res.safety };
    S.answers.unshift(a);
    pending.replaceWith(answerNode(a));
    highlight(res.region_ids);
  } catch (e) {
    pending.remove();
    const em = emergencyBox(e.data && e.data.safety);
    if (em) answers.prepend(em);
    status.textContent = errorText(e); status.hidden = false;
  }
}

function askBlock(answers) {
  const input = el("input", { class: "input", maxlength: 500, placeholder: t("askPh"), "aria-label": t("askTitle"), enterkeyhint: "send" });
  const status = el("p", { class: "error", role: "alert", hidden: true });
  const send = el("button", { class: "primary-btn", type: "button", text: t("askSend") });
  const submit = () => { const q = input.value.trim(); if (q.length < 2) { input.focus(); return; } input.value = ""; ask(q, false, answers, status); };
  send.addEventListener("click", submit);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });

  let mic = null;
  if (window.WavRecorder && WavRecorder.supported()) {
    let rec = null;
    mic = el("button", { class: "secondary-btn", type: "button", text: t("speak") });
    const stop = async () => {
      if (!rec) return;
      const r = rec; rec = null;
      mic.classList.remove("recording"); mic.textContent = t("understanding"); mic.disabled = true;
      try {
        const wav = await r.stop();
        const form = new FormData(); form.append("audio", wav, "question.wav");
        const res = await api("/api/vision/transcribe", { method: "POST", form, auth: true, timeout: SLOW });
        if (res.safety && res.safety.is_emergency) answers.prepend(emergencyBox(res.safety));
        if (res.text) await ask(res.text, true, answers, status);
      } catch (e) {
        const em = emergencyBox(e.data && e.data.safety);
        if (em) answers.prepend(em);
        status.textContent = errorText(e); status.hidden = false;
      } finally { mic.disabled = false; mic.textContent = t("speak"); }
    };
    mic.addEventListener("click", () => requireLogin(async () => {
      if (rec) { stop(); return; }
      try { rec = await WavRecorder.start(stop); }
      catch { status.textContent = t("micDenied"); status.hidden = false; return; }
      mic.classList.add("recording"); mic.textContent = `${t("listening")} ${t("stopRec")}`;
    }));
  }
  return el("section", { class: "card" },
    el("h2", { text: t("askTitle") }),
    el("div", { class: "ask-row" }, input, send),
    mic ? el("div", { class: "row" }, mic) : null,
    mic ? el("p", { class: "muted small", text: t("voiceBeta") }) : null,
    status, answers);
}

async function downloadPdf(btn) {
  btn.disabled = true; const label = btn.textContent; btn.textContent = t("making");
  try {
    const res = await api("/api/vision/pdf", { method: "POST", auth: true, raw: true, timeout: 60000,
      body: { lang: S.lang, district: S.district || null, document: docPayload() } });
    const url = URL.createObjectURL(await res.blob());
    const a = el("a", { href: url, download: "matrix-vision-summary.pdf" });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (e) { toast(errorText(e)); }
  finally { btn.disabled = false; btn.textContent = label; }
}

// ------------------------------------------------------------------ router and start

function route() {
  if (window.speechSynthesis) speechSynthesis.cancel();
  window.scrollTo(0, 0);
  if (location.hash.startsWith("#/result") && S.result) viewResult();
  else viewHome();
  $("view").focus({ preventScroll: true });
}

async function start() {
  renderHeader();
  try { S.cfg = await api("/api/config"); }
  catch (e) {
    render($("view"), el("div", { class: "card" }, el("p", { text: e.message }),
      el("button", { class: "secondary-btn", type: "button", text: t("tryAgain"), onclick: () => location.reload() })));
    return;
  }
  try { await initAuth(); } catch { /* Firebase not reachable: the page still works until scanning */ }
  renderHeader();
  $("langBtn").addEventListener("click", () => { S.lang = S.lang === "ne" ? "en" : "ne"; store.set("mv_lang", S.lang); renderHeader(); route(); });
  $("loginBtn").addEventListener("click", openLogin);
  $("logoutBtn").addEventListener("click", logout);
  $("googleBtn").addEventListener("click", googleLogin);
  $("devGo").addEventListener("click", devLogin);
  $("devName").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); devLogin(); } });
  $("loginCancel").addEventListener("click", () => $("loginSheet").close());
  $("loginSheet").addEventListener("close", () => { if (!S.user) afterLogin = null; });
  window.addEventListener("hashchange", route);
  route();
}
start();

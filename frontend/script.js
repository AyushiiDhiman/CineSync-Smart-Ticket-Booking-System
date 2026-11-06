/* ==========================================================================
   CineSync - Phase 4 frontend (plain JS, no build step)

   Flow: gate (name + location) -> cinemas near you -> showtimes ->
         seats -> pay -> ticket (+ snacks) -> my tickets / live chat
   ========================================================================== */

const API_BASE = "https://cinesync-smart-ticket-booking-system-2.onrender.com";
const MAX_GROUP_SEATS = 6;
const RING_LENGTH = 2 * Math.PI * 52;      // matches r=52 on the hold-timer ring
const LS_NAME = "cinesync.name";
const LS_LOC = "cinesync.loc";

const $ = id => document.getElementById(id);

// Everything that came from a user or the database goes through esc() before
// it touches innerHTML. (Phase 3 inserted chat messages and names raw, so a
// message like <img onerror=...> would have run script in everyone's browser.)
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  user: null,
  loc: null,                // { lat, lng, label, gps? }
  theatres: [], nearest: null,
  radius: 25, sort: "distance", amenities: new Set(),
  cinema: null, shows: [], day: null,
  show: null, seatsNeeded: 2, seats: [], seatsKey: "", selected: [],
  seatTimer: null, activityTimer: null,
  holdEndsAt: 0, holdSeconds: 300, holdTimer: null, holdActive: false, paying: false,
  order: null, lastBookingIds: [], food: {},
  movies: [], chatMovie: null, chatRating: 5, socket: null,
};

/* ----------------------------- helpers ----------------------------- */

async function api(path, opts = {}) {
  const res = await fetch(API_BASE + path, {
    method: opts.method || "GET",
    headers: { "Content-Type": "application/json" },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* non-JSON error body */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || `Request failed (${res.status})`);
    err.data = data;            // e.g. the transaction trace from a rolled-back payment
    throw err;
  }
  return data;
}

const money = n => "\u20b9" + Number(n).toLocaleString("en-IN");
const fmtTime = iso => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const dayKey = iso => iso.slice(0, 10);
const fmtDuration = m => `${Math.floor(m / 60)}h ${m % 60}m`;
const initials = name => name.trim().split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

function keyToDate(key) { const [y, m, d] = key.split("-").map(Number); return new Date(y, m - 1, d); }
function todayKey() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
function dayWord(key) {
  const diff = Math.round((keyToDate(key) - keyToDate(todayKey())) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  return keyToDate(key).toLocaleDateString([], { weekday: "long" });
}
const dayShort = key => keyToDate(key).toLocaleDateString([], { day: "numeric", month: "short" });

let toastTimer;
function toast(msg, kind) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast show" + (kind === "bad" ? " bad" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3400);
}

function hueFor(title) { let h = 0; for (const c of title) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }

// Posters are generated, not downloaded: colour comes from the title so a
// movie always looks the same, and the seat-map screen glows in that colour.
function posterHtml(title) {
  const h = hueFor(title);
  const letter = esc((title.trim()[0] || "?").toUpperCase());
  let holes = "";
  for (let i = 0; i < 12; i++) holes += `<rect x="6" y="${14 + i * 24}" width="8" height="12" rx="2"/><rect x="186" y="${14 + i * 24}" width="8" height="12" rx="2"/>`;
  return `<div class="poster" style="background:linear-gradient(160deg,hsl(${h} 78% 54%),hsl(${(h + 60) % 360} 70% 20%))">
    <svg viewBox="0 0 200 300" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <polygon points="40,0 150,0 230,300 -40,300" fill="#fff" opacity=".10"/>
      <g fill="#000" opacity=".28">${holes}</g>
      <text x="100" y="210" text-anchor="middle" font-family="Bricolage Grotesque, sans-serif" font-weight="800" font-size="150" fill="#fff" opacity=".92">${letter}</text>
    </svg></div>`;
}

function barcodeSvg(seed) {
  let x = 0, h = 7, rects = "";
  for (let i = 0; i < 46; i++) {
    h = (h * 31 + seed.charCodeAt(i % seed.length) + i) >>> 0;
    const w = 1 + (h % 3);
    if (i % 2 === 0) rects += `<rect x="${x}" y="0" width="${w}" height="40"/>`;
    x += w + (h % 2 ? 1 : 2);
  }
  return `<svg class="barcode" viewBox="0 0 ${x} 40" preserveAspectRatio="none" fill="currentColor" aria-hidden="true">${rects}</svg>`;
}

/* ----------------------------- theme (light / dark) ----------------------------- */

function currentTheme() { return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light"; }
function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("cinesync.theme", next); } catch (_) { /* private mode: just don't remember it */ }
  const label = next === "dark" ? "Switch to light mode" : "Switch to dark mode";
  ["themeBtn", "gateTheme"].forEach(id => { $(id).setAttribute("aria-label", label); $(id).title = label; });
}
$("themeBtn").addEventListener("click", toggleTheme);
$("gateTheme").addEventListener("click", toggleTheme);
(function syncThemeLabels() {
  const label = currentTheme() === "dark" ? "Switch to light mode" : "Switch to dark mode";
  ["themeBtn", "gateTheme"].forEach(id => { $(id).setAttribute("aria-label", label); $(id).title = label; });
})();

/* ----------------------------- navigation ----------------------------- */

const SCREENS = ["gate", "discover", "cinema", "seats", "pay", "done", "lab", "tickets", "chat"];
const NAV_OF = { gate: "discover", discover: "discover", cinema: "discover", seats: "discover", pay: "discover", done: "discover", lab: "lab", tickets: "tickets", chat: "chat" };

function go(id) {
  // leaving the payment screen without paying: give the seats back right away
  if (state.holdActive && !state.paying && id !== "pay") releaseHold();
  if (id !== "seats") { clearInterval(state.seatTimer); clearInterval(state.activityTimer); }
  if (id !== "pay") clearInterval(state.holdTimer);

  $("toast").classList.remove("show");
  SCREENS.forEach(s => $(s).classList.toggle("hidden", s !== id));
  $("topbar").classList.toggle("hidden", !state.user);
  $("gateTheme").classList.toggle("hidden", !!state.user);
  document.querySelectorAll(".nav button").forEach(b => b.classList.toggle("active", b.dataset.nav === NAV_OF[id]));
  window.scrollTo(0, 0);
}

document.querySelectorAll(".nav button").forEach(b => b.addEventListener("click", () => {
  if (b.dataset.nav === "discover") openDiscover();
  else if (b.dataset.nav === "tickets") loadTickets();
  else if (b.dataset.nav === "lab") openLab();
  else openChat();
}));
$("brandBtn").addEventListener("click", openDiscover);
$("locPill").addEventListener("click", openGate);

function updateTopbar() {
  $("userChip").textContent = state.user ? initials(state.user.name) : "";
  $("userChip").title = state.user ? state.user.name : "";
  $("locPillLabel").textContent = state.loc ? state.loc.label : "Set location";
}

/* ----------------------------- 1. gate: name + location ----------------------------- */

let pickedLoc = null, suggestItems = [], suggestIdx = -1, suggestTimer;

function openGate() {
  if (state.user) $("nameInput").value = state.user.name;
  if (state.loc) { $("locInput").value = state.loc.label; pickedLoc = state.loc; }
  $("gateGo").textContent = state.user ? "Update location" : "Show cinemas near me";
  $("gateMsg").textContent = "";
  go("gate");
}

function initGate() {
  const savedName = localStorage.getItem(LS_NAME);
  if (savedName) $("nameInput").value = savedName;
  try {
    const saved = JSON.parse(localStorage.getItem(LS_LOC) || "null");
    if (saved && typeof saved.lat === "number") { pickedLoc = saved; $("locInput").value = saved.label; }
  } catch (_) { /* ignore corrupt value */ }
}

function hideSuggest() { $("locSuggest").classList.add("hidden"); $("locInput").setAttribute("aria-expanded", "false"); suggestIdx = -1; }

function renderSuggest(q) {
  const items = suggestItems.map((s, i) =>
    `<li role="option" data-i="${i}" class="${i === suggestIdx ? "hl" : ""}"><span>${esc(s.label)}</span><small>${esc(s.sub || "")}</small></li>`);
  items.push(`<li role="option" class="web ${suggestIdx === suggestItems.length ? "hl" : ""}" data-web="1">Search the map for &ldquo;${esc(q)}&rdquo;</li>`);
  $("locSuggest").innerHTML = items.join("");
  $("locSuggest").classList.remove("hidden");
  $("locInput").setAttribute("aria-expanded", "true");
}

async function fetchSuggestions(q) {
  try { suggestItems = await api(`/api/locations/search?q=${encodeURIComponent(q)}`); }
  catch (_) { suggestItems = []; }
  // ignore stale responses (user kept typing)
  if ($("locInput").value.trim() === q) renderSuggest(q);
}

function pickLocation(loc) {
  pickedLoc = loc;
  $("locInput").value = loc.label;
  $("gateMsg").textContent = "";
  hideSuggest();
}

async function geocodeWeb(q) {
  // Fallback for anything we have no cinemas listed under (a pincode, a
  // landmark). OpenStreetMap's free Nominatim service - fine for a demo,
  // but it has a usage policy and rate limits, so use a paid geocoder
  // (or your own) before launching for real.
  const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=in&q=${encodeURIComponent(q)}`;
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  const hits = await res.json();
  if (!hits.length) throw new Error("not found");
  const label = hits[0].display_name.split(",").slice(0, 2).join(",").trim();
  return { lat: parseFloat(hits[0].lat), lng: parseFloat(hits[0].lon), label };
}

$("locInput").addEventListener("input", () => {
  pickedLoc = null;
  const q = $("locInput").value.trim();
  clearTimeout(suggestTimer);
  if (q.length < 2) { hideSuggest(); return; }
  suggestTimer = setTimeout(() => fetchSuggestions(q), 180);
});

$("locInput").addEventListener("keydown", e => {
  const open = !$("locSuggest").classList.contains("hidden");
  const total = suggestItems.length + 1;
  if (e.key === "ArrowDown" && open) { e.preventDefault(); suggestIdx = (suggestIdx + 1) % total; renderSuggest($("locInput").value.trim()); }
  else if (e.key === "ArrowUp" && open) { e.preventDefault(); suggestIdx = (suggestIdx - 1 + total) % total; renderSuggest($("locInput").value.trim()); }
  else if (e.key === "Escape") hideSuggest();
  else if (e.key === "Enter") {
    e.preventDefault();
    if (open && suggestIdx >= 0 && suggestIdx < suggestItems.length) pickLocation(suggestItems[suggestIdx]);
    else submitGate();
  }
});

$("locSuggest").addEventListener("click", async e => {
  const li = e.target.closest("li");
  if (!li) return;
  if (li.dataset.web) {
    const q = $("locInput").value.trim();
    hideSuggest();
    try { pickLocation(await geocodeWeb(q)); }
    catch (_) { $("gateMsg").textContent = "Couldn't find that place. Try a city name, or use your location."; }
  } else pickLocation(suggestItems[+li.dataset.i]);
});

document.addEventListener("click", e => { if (!e.target.closest(".loc-field")) hideSuggest(); });
$("nameInput").addEventListener("keydown", e => { if (e.key === "Enter") $("locInput").focus(); });

$("geoBtn").addEventListener("click", () => {
  if (!navigator.geolocation) { $("gateMsg").textContent = "This browser can't share location. Type your city or area instead."; return; }
  const btn = $("geoBtn");
  btn.disabled = true; btn.textContent = "Locating...";
  navigator.geolocation.getCurrentPosition(
    pos => {
      btn.disabled = false; btn.textContent = "Use my location";
      pickLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude, label: "Your location", gps: true });
    },
    err => {
      btn.disabled = false; btn.textContent = "Use my location";
      $("gateMsg").textContent = err.code === 1
        ? "Location permission was blocked. Type your city or area instead."
        : "Couldn't get your position. Type your city or area instead.";
    },
    { timeout: 10000, maximumAge: 300000 }
  );
});

$("gateGo").addEventListener("click", submitGate);

async function submitGate() {
  const msg = $("gateMsg");
  msg.textContent = "";
  const name = $("nameInput").value.trim();
  if (!name) { msg.textContent = "Enter your name so we can attach tickets to you."; $("nameInput").focus(); return; }

  const btn = $("gateGo");
  const idle = btn.textContent;
  btn.disabled = true; btn.textContent = "Finding cinemas...";
  hideSuggest();

  try {
    let loc = pickedLoc;
    const typed = $("locInput").value.trim();
    if (!loc && typed) {
      // typed a place but never clicked a suggestion: try our own list first, then the map
      try { const hits = await api(`/api/locations/search?q=${encodeURIComponent(typed)}`); if (hits[0]) loc = hits[0]; } catch (_) { /* fall through */ }
      if (!loc) {
        try { loc = await geocodeWeb(typed); }
        catch (_) { msg.textContent = "Couldn't find that place. Try a city name, or use your location."; return; }
      }
    }
    if (!loc) { msg.textContent = "Tell us where you are, or tap Use my location."; $("locInput").focus(); return; }

    if (!state.user || state.user.name !== name) state.user = await api("/api/users/lookup", { method: "POST", body: { name } });
    localStorage.setItem(LS_NAME, name);

    state.loc = { lat: loc.lat, lng: loc.lng, label: loc.label, gps: !!loc.gps };
    localStorage.setItem(LS_LOC, JSON.stringify(state.loc));
    ensureSocket();
    await loadDiscover();
  } catch (err) {
    msg.textContent = /fetch|network/i.test(err.message)
      ? "Couldn't reach the backend. Is app.py running on port 5000?"
      : err.message;
  } finally {
    btn.disabled = false; btn.textContent = idle;
  }
}

/* ----------------------------- 2. cinemas near you ----------------------------- */

function openDiscover() { if (!state.loc) openGate(); else if (!state.theatres.length) loadDiscover(); else { go("discover"); renderDiscover(); } }

async function loadDiscover() {
  go("discover");
  updateTopbar();
  $("discoverTitle").textContent = `Cinemas near ${state.loc.label}`;
  $("discoverSub").textContent = "";
  $("cinemaList").innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';

  // fetch everything once, sorted by distance; the radius slider then filters
  // on the client so it feels instant. (The endpoint also accepts radius_km.)
  const data = await api(`/api/theatres/nearby?lat=${state.loc.lat}&lng=${state.loc.lng}&radius_km=1000`);
  state.theatres = data.theatres;
  state.nearest = data.nearest;
  state.amenities.clear();

  if (state.nearest && state.loc.gps && state.nearest.distance_km <= 40) {
    state.loc.label = `Near ${state.nearest.city}`;
    updateTopbar();
    $("discoverTitle").textContent = `Cinemas near ${state.loc.label}`;
  }

  state.radius = autoRadius();
  renderDiscover();
}

// Smallest radius that still shows at least 3 cinemas (or all of them, if there
// are fewer). Keeps the radar readable instead of squashing everything into the middle.
function autoRadius() {
  if (!state.theatres.length) return 25;
  const want = Math.min(3, state.theatres.length);
  const ladder = [5, 10, 15, 25, 50, 100, 250, 500, 1000, 3000];
  for (const km of ladder) if (state.theatres.filter(t => t.distance_km <= km).length >= want) return km;
  return Math.ceil(state.theatres[state.theatres.length - 1].distance_km);
}

function visibleTheatres() {
  const inRange = state.theatres.filter(t => t.distance_km <= state.radius);
  const filtered = inRange.filter(t => [...state.amenities].every(a => t.amenities.includes(a)));
  const sorters = {
    distance: (a, b) => a.distance_km - b.distance_km,
    price: (a, b) => (a.from_price ?? 1e9) - (b.from_price ?? 1e9),
    time: (a, b) => (a.next_show || "9").localeCompare(b.next_show || "9"),
  };
  return { inRange, list: filtered.sort(sorters[state.sort]) };
}

// each cinema gets its own colour so the list reads at a glance
const CINEMA_HUES = [262, 335, 18, 195, 160, 285, 215, 350];

function nextShowLabel(iso) { return iso ? `${dayWord(dayKey(iso))}, ${fmtTime(iso)}` : null; }

function renderDiscover() {
  const slider = $("radiusRange");
  slider.max = Math.max(100, state.radius);
  slider.value = state.radius;
  $("radiusVal").textContent = state.radius;

  const { inRange, list } = visibleTheatres();

  const allAmenities = [...new Set(inRange.flatMap(t => t.amenities))].sort();
  $("amenityChips").innerHTML = allAmenities.map(a =>
    `<button class="chip ${state.amenities.has(a) ? "on" : ""}" data-amenity="${esc(a)}" aria-pressed="${state.amenities.has(a)}">${esc(a)}</button>`).join("");

  $("discoverSub").textContent = list.length
    ? `${plural(list.length, "cinema")} within ${state.radius} km`
    : "";

  if (!list.length) {
    const n = state.nearest;
    const reason = inRange.length ? "No cinema matches those amenities." : `No cinemas within ${state.radius} km.`;
    $("cinemaList").innerHTML = `<div class="empty">
      <h3>${reason}</h3>
      <p>${n ? `The closest one is ${esc(n.name)} in ${esc(n.city)}, ${n.distance_km} km away.` : "There are no cinemas in the database yet."}</p>
      ${inRange.length && state.amenities.size ? '<button class="btn ghost" id="clearFilters">Clear amenity filters</button>'
        : n ? `<button class="btn primary" id="widenRadius" data-km="${Math.ceil(n.distance_km)}">Widen to ${Math.ceil(n.distance_km)} km</button>` : ""}
    </div>`;
  } else {
    const nearestId = [...list].sort((a, b) => a.distance_km - b.distance_km)[0].id;
    $("cinemaList").innerHTML = list.map(t => {
      const next = nextShowLabel(t.next_show);
      return `<article class="ticket ${t.id === nearestId ? "nearest" : ""}" style="--h:${CINEMA_HUES[t.id % CINEMA_HUES.length]}" data-id="${t.id}" tabindex="0" role="button" aria-label="${esc(t.name)}, ${t.distance_km} kilometres away">
        <div class="ticket-stub"><b>${t.distance_km}</b><span>km away</span></div>
        <div class="ticket-main">
          <h3>${esc(t.name)}${t.id === nearestId ? '<span class="badge">closest</span>' : ""}</h3>
          <div class="where">${esc(t.location)}, ${esc(t.city)}</div>
          <div class="facts">
            ${t.movie_count ? `<span><b>${t.movie_count}</b> movies</span>` : "<span>No upcoming shows</span>"}
            ${t.from_price != null ? `<span>from <b>${money(t.from_price)}</b></span>` : ""}
            ${next ? `<span>next <b>${esc(next)}</b></span>` : ""}
          </div>
          <div class="mini-chips">${t.amenities.map(a => `<span>${esc(a)}</span>`).join("")}</div>
        </div></article>`;
    }).join("");
  }
  renderRadar(list);
}

$("radiusRange").addEventListener("input", e => { state.radius = +e.target.value; renderDiscover(); });
$("sortSeg").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  state.sort = b.dataset.sort;
  document.querySelectorAll("#sortSeg button").forEach(x => x.classList.toggle("on", x === b));
  renderDiscover();
});
$("amenityChips").addEventListener("click", e => {
  const b = e.target.closest("[data-amenity]"); if (!b) return;
  const a = b.dataset.amenity;
  state.amenities.has(a) ? state.amenities.delete(a) : state.amenities.add(a);
  renderDiscover();
});
$("cinemaList").addEventListener("click", e => {
  if (e.target.closest("#widenRadius")) { state.radius = +e.target.closest("#widenRadius").dataset.km; renderDiscover(); return; }
  if (e.target.closest("#clearFilters")) { state.amenities.clear(); renderDiscover(); return; }
  const card = e.target.closest(".ticket"); if (card) openCinema(+card.dataset.id);
});
$("cinemaList").addEventListener("keydown", e => {
  if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("ticket")) { e.preventDefault(); openCinema(+e.target.dataset.id); }
});

// hovering a cinema lights its pin on the radar, and the other way round
function highlight(id, on) {
  document.querySelectorAll(`.ticket[data-id="${id}"], .r-pin[data-id="${id}"]`).forEach(el => el.classList.toggle("hl", on));
}
$("cinemaList").addEventListener("mouseover", e => { const c = e.target.closest(".ticket"); if (c) highlight(c.dataset.id, true); });
$("cinemaList").addEventListener("mouseout", e => { const c = e.target.closest(".ticket"); if (c) highlight(c.dataset.id, false); });
$("radar").addEventListener("mouseover", e => { const p = e.target.closest(".r-pin"); if (p) highlight(p.dataset.id, true); });
$("radar").addEventListener("mouseout", e => { const p = e.target.closest(".r-pin"); if (p) highlight(p.dataset.id, false); });
$("radar").addEventListener("click", e => { const p = e.target.closest(".r-pin"); if (p) openCinema(+p.dataset.id); });

function niceKm(v) { return v >= 10 ? Math.round(v) : Math.round(v * 10) / 10; }

function renderRadar(list) {
  const C = 200, R = 170, rad = state.radius;
  let out = "";
  [1, 2, 3].forEach(i => {
    out += `<circle class="r-ring" cx="${C}" cy="${C}" r="${R * i / 3}"/>`;
    out += `<text class="r-label" x="${C + 5}" y="${C + R * i / 3 - 4}">${niceKm(rad * i / 3)} km</text>`;
  });
  out += `<text class="r-north" x="${C}" y="20">N</text>`;

  const cosLat = Math.cos(state.loc.lat * Math.PI / 180);
  list.forEach(t => {
    // bearing from you to the cinema; length comes from the real distance
    const dx = (t.lng - state.loc.lng) * cosLat * 111.32;
    const dy = (t.lat - state.loc.lat) * 110.57;
    const ang = Math.atan2(dx, dy);
    const r = Math.min(t.distance_km / rad, 1) * R;
    const x = C + r * Math.sin(ang), y = C - r * Math.cos(ang);
    const right = x > C + 40;
    out += `<g class="r-pin" style="--h:${CINEMA_HUES[t.id % CINEMA_HUES.length]}" data-id="${t.id}" tabindex="0" role="button" aria-label="${esc(t.name)}, ${t.distance_km} km">
      <circle class="halo" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="17"/>
      <circle class="dot" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="6"/>
      <text x="${(x + (right ? -12 : 12)).toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="${right ? "end" : "start"}">${esc(t.name)}</text></g>`;
  });

  out += `<circle class="r-you-pulse" cx="${C}" cy="${C}" r="6"/><circle class="r-you" cx="${C}" cy="${C}" r="6"/>`;
  $("radar").innerHTML = out;
}

/* ----------------------------- 3. one cinema: days, movies, showtimes ----------------------------- */

async function openCinema(id) {
  const t = state.theatres.find(x => x.id === id);
  state.cinema = t;
  $("cinemaName").textContent = t.name;
  $("cinemaMeta").textContent = `${t.location}, ${t.city}  \u00b7  ${t.distance_km} km from ${state.loc.label}`;
  $("cinemaAmenities").innerHTML = t.amenities.map(a => `<span class="chip">${esc(a)}</span>`).join("");
  $("dayTabs").innerHTML = "";
  $("movieRows").innerHTML = '<div class="skeleton"></div>';
  go("cinema");

  try {
    state.shows = await api(`/api/theatres/${id}/shows`);
  } catch (err) { $("movieRows").innerHTML = `<div class="empty"><h3>Couldn't load showtimes</h3><p>${esc(err.message)}</p></div>`; return; }

  if (!state.shows.length) {
    $("movieRows").innerHTML = `<div class="empty"><h3>No upcoming shows</h3><p>Run <code>python seed_shows.py</code> in the backend folder to generate the next few days of shows.</p></div>`;
    return;
  }
  const days = [...new Set(state.shows.map(s => dayKey(s.show_time)))].sort();
  state.day = days[0];
  renderDays(days);
  renderMovies();
}

function renderDays(days) {
  $("dayTabs").innerHTML = days.map(d =>
    `<button class="day-tab ${d === state.day ? "on" : ""}" data-day="${d}" role="tab"><small>${dayWord(d)}</small><b>${dayShort(d)}</b></button>`).join("");
}
$("dayTabs").addEventListener("click", e => {
  const b = e.target.closest(".day-tab"); if (!b) return;
  state.day = b.dataset.day;
  document.querySelectorAll(".day-tab").forEach(x => x.classList.toggle("on", x === b));
  renderMovies();
});

function renderMovies() {
  const todays = state.shows.filter(s => dayKey(s.show_time) === state.day);
  const byMovie = new Map();
  todays.forEach(s => { if (!byMovie.has(s.movie_id)) byMovie.set(s.movie_id, []); byMovie.get(s.movie_id).push(s); });

  $("movieRows").innerHTML = [...byMovie.values()].map(shows => {
    const m = shows[0];
    const meta = [m.genre, m.language, fmtDuration(m.duration_min)].filter(Boolean).join("  \u00b7  ");
    const chips = shows.map(s => {
      const pct = s.total_seats ? s.available_seats / s.total_seats : 0;
      const cls = s.available_seats === 0 ? "" : pct <= 0.15 ? "low" : pct <= 0.5 ? "fast" : "ok";
      const note = s.available_seats === 0 ? "Sold out" : cls === "ok" ? `from ${money(s.price)}` : `${s.available_seats} left`;
      return `<button class="time-chip ${cls}" data-show="${s.show_id}" ${s.available_seats === 0 ? "disabled" : ""}>
        <b>${fmtTime(s.show_time)}</b><small>${note}</small>
        <span class="bar"><i style="width:${Math.round(pct * 100)}%"></i></span></button>`;
    }).join("");
    return `<div class="movie-row">${posterHtml(m.title)}<div><h3>${esc(m.title)}</h3><p class="movie-meta">${esc(meta)}</p><div class="times">${chips}</div></div></div>`;
  }).join("") || '<div class="empty"><h3>Nothing left today</h3><p>Pick another day above.</p></div>';
}

$("movieRows").addEventListener("click", e => {
  const b = e.target.closest(".time-chip"); if (!b || b.disabled) return;
  openSeats(state.shows.find(s => s.show_id === +b.dataset.show));
});
$("backToDiscover").addEventListener("click", () => { go("discover"); renderDiscover(); });

/* ----------------------------- 4. seats ----------------------------- */

function openSeats(show) {
  state.show = show;
  state.selected = [];
  state.seats = [];
  state.seatsKey = "";
  $("seats").style.setProperty("--hue", hueFor(show.title));
  $("seatMovie").textContent = show.title;
  $("seatMeta").textContent = `${state.cinema.name}  \u00b7  ${dayWord(dayKey(show.show_time))}, ${fmtTime(show.show_time)}`;
  $("seatMap").innerHTML = '<div class="skeleton" style="width:420px;max-width:90vw"></div>';
  $("seatCount").textContent = state.seatsNeeded;
  updateStepper();
  updateTray();
  go("seats");

  loadSeats();
  loadActivity();
  state.seatTimer = setInterval(loadSeats, 3000);
  state.activityTimer = setInterval(() => { if ($("activity").open) loadActivity(); }, 2000);
}

async function loadSeats() {
  if (!state.show) return;
  let data;
  try { data = await api(`/api/shows/${state.show.show_id}/seats`); } catch (_) { return; }
  const key = JSON.stringify(data);
  if (key === state.seatsKey) return;       // nothing changed: don't redraw (keeps hover/animations steady)
  state.seatsKey = key;
  state.seats = data;

  // live concurrency: if someone else grabbed a seat I'd picked, say so and drop it
  const me = state.user.id;
  const lost = state.selected.filter(sel => {
    const s = data.find(x => x.id === sel.id);
    return !s || s.status === "booked" || (s.status === "held" && s.held_by !== me);
  });
  if (lost.length) {
    state.selected = state.selected.filter(sel => !lost.includes(sel));
    toast(`${lost.map(l => l.seatNo).join(", ")} just got taken by someone else`, "bad");
    updateTray();
  }
  renderSeats();
}

async function loadActivity() {
  try {
    const entries = await api("/api/activity-log");
    $("activityLog").innerHTML = entries.length
      ? entries.map(e => `<div><time>${esc(e.time)}</time>${esc(e.message)}</div>`).join("")
      : "<div>No activity yet. Pick seats and continue to see locking in action.</div>";
  } catch (_) { /* panel is optional */ }
}

function groupRows(seats) {
  const rows = {};
  seats.forEach(s => {
    const m = /^([A-Z]+)(\d+)$/.exec(s.seat_no);
    if (m) (rows[m[1]] = rows[m[1]] || []).push({ ...s, row: m[1], num: +m[2] });
  });
  Object.values(rows).forEach(r => r.sort((a, b) => a.num - b.num));
  return rows;
}

const isPickable = s => s.status === "available" || (s.status === "held" && s.held_by === state.user.id);

function renderSeats() {
  const rows = groupRows(state.seats);
  const names = Object.keys(rows).sort();
  if (!names.length) { $("seatMap").innerHTML = '<div class="empty">No seats for this show.</div>'; return; }
  const cols = Math.max(...names.map(r => rows[r].length));
  const aisleAfter = Math.ceil(cols / 2);
  const chosen = new Set(state.selected.map(s => s.id));

  let html = '<div class="seat-rows">', lastTier = null;
  names.forEach(r => {
    const first = rows[r][0];
    if (first.tier !== lastTier) { html += `<div class="tier-label"><b>${esc(first.tier)}</b> ${money(first.price)}</div>`; lastTier = first.tier; }
    html += `<div class="seat-row"><span class="row-name">${r}</span>`;
    rows[r].forEach(s => {
      if (s.num === aisleAfter + 1) html += '<span class="aisle"></span>';
      const sel = chosen.has(s.id);
      let cls = sel ? "selected" : s.status === "held" && s.held_by === state.user.id ? "available mine" : s.status;
      const ok = sel || isPickable(s);
      const label = sel ? "selected" : s.status === "held" ? "held by someone paying" : s.status;
      html += `<button class="seat ${cls}" data-id="${s.id}" ${ok ? "" : "disabled"} aria-pressed="${sel}"
        title="${s.seat_no} \u00b7 ${esc(s.tier)} \u00b7 ${money(s.price)}" aria-label="Seat ${s.seat_no}, ${esc(s.tier)}, ${money(s.price)}, ${label}">${s.num}</button>`;
    });
    html += `<span class="row-name">${r}</span></div>`;
  });
  $("seatMap").innerHTML = html + "</div>";
}

$("seatMap").addEventListener("click", e => {
  const b = e.target.closest(".seat"); if (!b || b.disabled) return;
  toggleSeat(+b.dataset.id);
});

function toggleSeat(id) {
  const i = state.selected.findIndex(s => s.id === id);
  if (i >= 0) state.selected.splice(i, 1);
  else {
    if (state.selected.length >= state.seatsNeeded) { toast(`You asked for ${plural(state.seatsNeeded, "seat")}. Remove one, or raise the seat count.`, "bad"); return; }
    const s = state.seats.find(x => x.id === id);
    state.selected.push({ id: s.id, seatNo: s.seat_no, price: s.price, tier: s.tier });
  }
  renderSeats();
  updateTray();
}

function updateStepper() {
  $("seatCount").textContent = state.seatsNeeded;
  $("seatMinus").disabled = state.seatsNeeded <= 1;
  $("seatPlus").disabled = state.seatsNeeded >= MAX_GROUP_SEATS;
}
$("seatMinus").addEventListener("click", () => setSeatCount(state.seatsNeeded - 1));
$("seatPlus").addEventListener("click", () => setSeatCount(state.seatsNeeded + 1));

function setSeatCount(n) {
  state.seatsNeeded = Math.max(1, Math.min(MAX_GROUP_SEATS, n));
  if (state.selected.length > state.seatsNeeded) state.selected.length = state.seatsNeeded;
  updateStepper();
  renderSeats();
  updateTray();
}

function updateTray() {
  const sel = state.selected, need = state.seatsNeeded;
  $("tray").classList.toggle("show", sel.length > 0);
  $("traySeats").innerHTML = sel.map(s => `<span>${s.seatNo}</span>`).join("");
  $("trayTotal").textContent = money(sel.reduce((t, s) => t + s.price, 0));
  const btn = $("continueBtn");
  btn.disabled = sel.length !== need;
  btn.textContent = sel.length === need ? "Hold seats and pay" : `Pick ${plural(need - sel.length, "more seat")}`;
}

// "Pick best seats": the closest block of N free seats to the centre of the
// hall, a little behind the middle row (that's where the screen fills your
// view without craning your neck)
$("bestSeatsBtn").addEventListener("click", () => {
  const n = state.seatsNeeded;
  const rows = groupRows(state.seats);
  const names = Object.keys(rows).sort();
  if (!names.length) return;
  const cols = Math.max(...names.map(r => rows[r].length));
  const aisleAfter = Math.ceil(cols / 2);
  const idealRow = Math.round((names.length - 1) * 0.6);

  let best = null;
  names.forEach((r, ri) => {
    const arr = rows[r];
    for (let i = 0; i + n <= arr.length; i++) {
      const block = arr.slice(i, i + n);
      if (!block.every(isPickable)) continue;
      const centre = block.reduce((t, s) => t + s.num, 0) / n;
      const crossesAisle = block[0].num <= aisleAfter && block[n - 1].num > aisleAfter;
      const score = Math.abs(centre - (cols + 1) / 2) + 1.6 * Math.abs(ri - idealRow) + (crossesAisle ? 1 : 0);
      if (!best || score < best.score) best = { score, block };
    }
  });

  if (!best) { toast(`No block of ${n} seats together is free. Pick seats one by one.`, "bad"); return; }
  state.selected = best.block.map(s => ({ id: s.id, seatNo: s.seat_no, price: s.price, tier: s.tier }));
  renderSeats();
  updateTray();
  toast(`Picked ${state.selected.map(s => s.seatNo).join(", ")}`);
});

$("backToCinema").addEventListener("click", () => go("cinema"));

$("continueBtn").addEventListener("click", async () => {
  const btn = $("continueBtn");
  btn.disabled = true; btn.textContent = "Locking seats...";
  try {
    const d = await api(`/api/shows/${state.show.show_id}/hold-group`, {
      method: "POST", body: { user_id: state.user.id, seat_ids: state.selected.map(s => s.id) },
    });
    state.holdSeconds = d.hold_seconds || 300;
    state.holdEndsAt = Date.now() + state.holdSeconds * 1000;
    state.holdActive = true;
    openPay();
  } catch (err) {
    toast(err.message, "bad");
    state.selected = [];
    state.seatsKey = "";
    await loadSeats();
    updateTray();
  }
});

/* ----------------------------- 5. pay ----------------------------- */

function openPay() {
  const s = state.show, sel = state.selected;
  const total = sel.reduce((t, x) => t + x.price, 0);
  const tiers = {};
  sel.forEach(x => { (tiers[x.tier] = tiers[x.tier] || { n: 0, sum: 0 }); tiers[x.tier].n++; tiers[x.tier].sum += x.price; });

  $("paySummary").innerHTML = `
    <div class="sum-movie">${posterHtml(s.title)}
      <div><h2>${esc(s.title)}</h2>
        <p class="sub">${esc(state.cinema.name)}, ${esc(state.cinema.city)}</p>
        <p class="sub">${dayWord(dayKey(s.show_time))}, ${dayShort(dayKey(s.show_time))} at ${fmtTime(s.show_time)}</p>
        <p class="sub">Seats ${sel.map(x => esc(x.seatNo)).join(", ")}</p></div></div>
    <div class="sum-lines">
      ${Object.entries(tiers).map(([t, v]) => `<div class="sum-line"><span>${esc(t)} \u00d7 ${v.n}</span><span>${money(v.sum)}</span></div>`).join("")}
      <div class="sum-line total"><span>Total</span><span>${money(total)}</span></div>
    </div>`;

  $("payMsg").textContent = "";
  $("payBtn").disabled = false;
  state.payLabel = `Pay ${money(total)}`;
  $("payBtn").textContent = state.payLabel;
  state.paying = false;
  go("pay");
  tickHold();
  state.holdTimer = setInterval(tickHold, 1000);
}

function tickHold() {
  const left = Math.max(0, Math.ceil((state.holdEndsAt - Date.now()) / 1000));
  $("holdTime").textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  $("ringFg").style.strokeDashoffset = RING_LENGTH * (1 - left / state.holdSeconds);
  $("holdRing").classList.toggle("warn", left <= 120 && left > 45);
  $("holdRing").classList.toggle("crit", left <= 45);

  if (left === 0 && !state.paying) {
    clearInterval(state.holdTimer);
    releaseHold();
    toast("Your hold expired and the seats were released", "bad");
    backToSeats();
  }
}

async function releaseHold() {
  if (!state.holdActive) return;
  state.holdActive = false;
  try { await api("/api/holds/release", { method: "POST", body: { user_id: state.user.id, seat_ids: state.selected.map(s => s.id) } }); }
  catch (_) { /* the scheduler frees it within 30 s anyway */ }
}

function backToSeats() {
  go("seats");
  state.seatsKey = "";
  loadSeats(); loadActivity();
  state.seatTimer = setInterval(loadSeats, 3000);
  state.activityTimer = setInterval(() => { if ($("activity").open) loadActivity(); }, 2000);
  updateTray();
}

$("payCancel").addEventListener("click", async () => { await releaseHold(); backToSeats(); });

$("payBtn").addEventListener("click", async () => {
  const btn = $("payBtn"), msg = $("payMsg");
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = "Opening checkout...";
  msg.textContent = "";
  $("txViewer").classList.add("hidden");
  const reset = () => { btn.disabled = false; btn.textContent = label; state.paying = false; };

  let order;
  try {
    // we send NO amount: the server prices the seats itself
    order = await api("/api/payment/create-order", { method: "POST", body: { user_id: state.user.id, seat_ids: state.selected.map(s => s.id) } });
  } catch (err) { msg.textContent = err.message; reset(); return; }

  state.paying = true;

  if (order.mode === "mock") {
    // demo checkout: same flow as Razorpay (order -> pay -> verify), no gateway
    $("payHint").textContent = "Demo mode: no real money moves. You can make the payment succeed, decline, or crash the server halfway to see ACID at work.";
    openMockCheckout(order, reset);
    return;
  }
  $("payHint").textContent = "Razorpay test mode: card 4111 1111 1111 1111, any future expiry, any CVV.";

  if (typeof Razorpay === "undefined") { msg.textContent = "Razorpay checkout didn't load. Check your internet connection and try again."; reset(); return; }

  const rzp = new Razorpay({
    key: order.key_id, amount: order.amount, currency: "INR", name: "CineSync",
    description: `${state.show.title}, ${plural(state.selected.length, "seat")}`,
    order_id: order.order_id, prefill: { name: state.user.name }, theme: { color: "#ff5c8a" },
    handler: resp => verifyPayment(resp, order),
    modal: { ondismiss: () => { msg.textContent = "Payment window closed. Your seats are still held."; reset(); } },
  });
  rzp.on("payment.failed", r => { msg.textContent = `Payment failed: ${r.error.description}`; reset(); });
  rzp.open();
});

function openMockCheckout(order, reset) {
  const close = () => $("mockModal").classList.add("hidden");
  $("mockAmount").textContent = money(order.amount_rupees);
  $("mockModal").classList.remove("hidden");
  $("mockPay").focus();

  const run = outcome => {
    close();
    verifyPayment({
      razorpay_order_id: order.order_id,
      razorpay_payment_id: "mock_pay_" + Math.random().toString(36).slice(2, 12),
      razorpay_signature: "mock",
      outcome,                       // the SERVER decides what that means: commit, decline or crash + rollback
    }, order);
  };
  $("mockPay").onclick = () => run("success");
  $("mockFail").onclick = () => run("decline");
  $("mockCrash").onclick = () => run("crash");
  $("mockCancel").onclick = () => { close(); $("payMsg").textContent = "Payment window closed. Your seats are still held."; reset(); };
}

async function verifyPayment(resp, order) {
  $("payMsg").textContent = "Verifying payment...";
  $("txViewer").classList.add("hidden");
  try {
    const data = await api("/api/payment/verify", { method: "POST", body: {
      razorpay_order_id: resp.razorpay_order_id,
      razorpay_payment_id: resp.razorpay_payment_id,
      razorpay_signature: resp.razorpay_signature,
      outcome: resp.outcome,
    } });
    state.holdActive = false;
    state.paying = false;
    openDone(data, resp.razorpay_payment_id, order.amount_rupees);
  } catch (err) {
    state.paying = false;
    $("payBtn").disabled = false;
    $("payBtn").textContent = state.payLabel;      // was "Opening checkout..."
    const d = err.data || {};
    $("payMsg").textContent = d.trace ? "" : `Verification failed: ${err.message}`;
    if (d.trace) {
      const kind = d.rolled_back ? "crash" : resp.outcome === "decline" ? "decline" : "error";
      showTx($("txViewer"), d, kind, err.message);
      $("txViewer").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
}

/* ----------------------------- transaction timeline (shared by pay, done and the lab) ----------------------------- */

const KIND_LABEL = { sql: "SQL", lock: "LOCK", ok: "OK", wait: "WAIT", error: "ERROR", rollback: "ROLLBACK", commit: "COMMIT", crash: "CRASH", info: "NOTE", gateway: "BANK" };

function timelineHtml(steps) {
  const actors = steps.some(x => x.actor);
  return `<div class="tl ${actors ? "" : "noactor"}">` + steps.map((x, i) => `
    <div class="tl-step" data-kind="${esc(x.kind)}" style="animation-delay:${Math.min(i * 110, 2400)}ms">
      <span class="tl-t">${x.t != null ? x.t.toFixed(1) + "s" : ""}</span>
      <span class="tl-actor" style="--h:${hueFor(x.actor || "")}">${esc(x.actor || "")}</span>
      <span class="tl-kind">${KIND_LABEL[x.kind] || ""}</span>
      <span class="tl-text">${esc(x.text)}</span>
    </div>`).join("") + "</div>";
}

function stateChipsHtml(st) {
  if (!st) return "";
  return `<div class="kv">
    <span>Order <b>${esc(st.order_status)}</b></span>
    <span>Bookings saved <b>${st.bookings}</b></span>
    <span>Payments saved <b>${st.payments}</b></span>
    ${st.seats.map(x => `<span class="${esc(x.status)}">Seat ${esc(x.seat_no)} <b>${esc(x.status)}</b></span>`).join("")}</div>`;
}

// kind: "success" (COMMIT), "crash" (ROLLBACK), "decline", "error"
function showTx(el, data, kind, headline) {
  const st = data.state_after;
  const words = {
    success: ["ok", "Durability: committed means kept",
      "These numbers were read back through a brand-new database connection after COMMIT, so they are the permanent, saved state. Atomicity held too: every seat, booking and payment was written together."],
    crash: ["ok", "Atomicity: the crash left nothing behind",
      "The first seat's booking and payment were written, then the server died before COMMIT. ROLLBACK undid all of it: the numbers above show no bookings, no payments, and the seats are still held for you. Press Pay again to retry."],
    decline: ["ok", "No money, no booking",
      "The booking transaction only starts after payment is confirmed, so a declined card never touches the bookings table. Your seats are still held; press Pay to try again."],
    error: ["bad", "The transaction was rejected", headline || "Something went wrong, and the database kept nothing."],
  }[kind] || ["bad", "Rejected", headline || ""];
  el.innerHTML = `<h3>What the database just did</h3>${timelineHtml(data.trace || [])}${stateChipsHtml(st)}
    <div class="verdict ${words[0]}"><span class="mark">${words[0] === "ok" ? "\u2713" : "!"}</span><div><b>${esc(words[1])}</b><p>${esc(words[2])}</p></div></div>`;
  el.classList.remove("hidden");
}

/* ----------------------------- 6. confirmed ticket + snacks ----------------------------- */

function bigTicketHtml(t, small) {
  return `<article class="big-ticket ${small ? "small" : ""} ${t.past ? "past" : ""}">
    <div class="big-stub">${barcodeSvg(t.ref)}<small>${esc(t.ref)}</small></div>
    <div class="big-main">
      <h2>${esc(t.title)}</h2>
      <div class="big-grid">
        <div><small>Cinema</small><b>${esc(t.cinema)}</b></div>
        <div><small>Showtime</small><b>${esc(t.when)}</b></div>
        <div><small>Seats</small><b>${esc(t.seats)}</b></div>
        <div><small>${t.state && t.state !== "confirmed" ? esc(t.state) : "Paid"}</small><b>${t.amount != null ? money(t.amount) : "-"}</b></div>
      </div></div></article>`;
}

function openDone(data, paymentId, amount) {
  state.lastBookingIds = data.booking_ids;
  state.food = {};
  const s = state.show;
  $("ticketMount").innerHTML = bigTicketHtml({
    ref: "CS" + String(data.group_order_id).padStart(5, "0"),
    title: s.title,
    cinema: `${state.cinema.name}, ${state.cinema.city}`,
    when: `${dayWord(dayKey(s.show_time))}, ${fmtTime(s.show_time)}`,
    seats: state.selected.map(x => x.seatNo).join(", "),
    amount,
  });
  showTx($("doneTx"), data, "success");
  $("doneTx").querySelector("h3").textContent = "Your booking, step by step";
  $("foodMsg").textContent = "";
  $("addFoodBtn").disabled = false;
  $("addFoodBtn").textContent = "Add to order";
  loadFood();
  go("done");
}

async function loadFood() {
  $("foodList").innerHTML = '<div class="skeleton"></div>';
  try {
    const items = await api("/api/food-items");
    $("foodList").innerHTML = items.map(i => `
      <div class="food-item" data-id="${i.id}"><div><b>${esc(i.name)}</b><small>${money(i.price)}</small></div>
        <div class="mini-step"><button data-d="-1" aria-label="Remove one ${esc(i.name)}">&minus;</button><span>0</span><button data-d="1" aria-label="Add one ${esc(i.name)}">+</button></div></div>`).join("");
    state.foodPrices = Object.fromEntries(items.map(i => [i.id, +i.price]));
  } catch (_) { $("foodList").innerHTML = "<p class='sub'>Couldn't load the menu.</p>"; }
}

$("foodList").addEventListener("click", e => {
  const b = e.target.closest("button[data-d]"); if (!b) return;
  const row = b.closest(".food-item"), id = row.dataset.id;
  state.food[id] = Math.max(0, Math.min(10, (state.food[id] || 0) + +b.dataset.d));
  row.querySelector("span").textContent = state.food[id];
  row.classList.toggle("has", state.food[id] > 0);
  const total = Object.entries(state.food).reduce((t, [k, q]) => t + q * state.foodPrices[k], 0);
  $("addFoodBtn").textContent = total ? `Add to order \u00b7 ${money(total)}` : "Add to order";
});

$("addFoodBtn").addEventListener("click", async () => {
  const items = Object.entries(state.food).filter(([, q]) => q > 0).map(([id, q]) => ({ food_item_id: +id, quantity: q }));
  if (!items.length) { $("foodMsg").textContent = "Pick at least one item, or skip."; return; }
  try {
    // Phase 3 behaviour kept: food hangs off the first booking in the group
    await api(`/api/bookings/${state.lastBookingIds[0]}/food-order`, { method: "POST", body: { items } });
    $("foodMsg").textContent = ""; $("addFoodBtn").disabled = true;
    toast("Snacks added. Enjoy the movie!");
  } catch (err) { $("foodMsg").textContent = err.message; }
});
$("finishBtn").addEventListener("click", loadTickets);

/* ----------------------------- ACID lab ----------------------------- */

const LAB = {
  atomicity: {
    letter: "A", hue: 335, name: "Atomicity",
    promise: "All the steps happen, or none do.",
    story: "Priya books 3 seats in one go. The server crashes after the 2nd seat has been written. What is left in the database?",
    where: "In app.py: _confirm_booking() starts with BEGIN, writes every seat, and only calls COMMIT at the very end. Any failure runs ROLLBACK.",
    modes: [{ id: "safe", label: "With a transaction" }, { id: "unsafe", label: "Without (autocommit)" }],
    call: m => api("/api/acid/atomicity", { method: "POST", body: { safe: m === "safe" } }),
  },
  consistency: {
    letter: "C", hue: 262, name: "Consistency",
    promise: "The database never breaks its own rules.",
    story: "The tables have rules: a seat can only be booked once (UNIQUE) and a wallet can never go below zero (CHECK). Try to break them.",
    where: "In the schema: UNIQUE and CHECK constraints. In app.py: a seat may only become 'booked' if it is held by the same user.",
    modes: [{ id: "double_booking", label: "Book a taken seat" }, { id: "overdraft", label: "Overspend the wallet" }],
    call: m => api("/api/acid/consistency", { method: "POST", body: { scenario: m } }),
  },
  isolation: {
    letter: "I", hue: 195, name: "Isolation",
    promise: "Simultaneous bookings don't trip over each other.",
    story: "Priya and Rohan both press 'book' on seat L1 at almost the same moment. Who gets it, and does the database stay honest?",
    where: "In app.py: hold_group() uses SELECT ... FOR UPDATE and locks seats in sorted ID order, so two groups can't grab the same seat or deadlock.",
    modes: [{ id: "safe", label: "With row locks" }, { id: "unsafe", label: "Without locks" }],
    call: m => api("/api/acid/isolation", { method: "POST", body: { safe: m === "safe" } }),
  },
  durability: {
    letter: "D", hue: 150, name: "Durability",
    promise: "Once committed, it stays committed.",
    story: "Priya's booking is committed. We read it back through a brand-new connection, then look at the setting that decides whether it would survive a crash.",
    where: "InnoDB writes every committed transaction to its redo log on disk. app.py only tells the user 'confirmed' after conn.commit() returns.",
    modes: null,
    call: () => api("/api/acid/durability", { method: "POST" }),
  },
};

state.lab = { tab: "atomicity", mode: { atomicity: "safe", consistency: "double_booking", isolation: "safe" }, running: false };

function openLab() {
  go("lab");
  renderLab();
}

function renderLab() {
  const t = state.lab.tab, def = LAB[t];
  $("labTabs").innerHTML = Object.entries(LAB).map(([id, d]) => `
    <button class="lab-tab ${id === t ? "on" : ""}" data-tab="${id}" style="--h:${d.hue}" role="tab" aria-selected="${id === t}">
      <span class="letter">${d.letter}</span><b>${d.name}</b><span class="p">${esc(d.promise)}</span></button>`).join("");

  const modes = def.modes ? `<div class="seg" id="labModes" role="group" aria-label="Mode">
      ${def.modes.map(m => `<button data-mode="${m.id}" class="${state.lab.mode[t] === m.id ? "on" : ""}">${esc(m.label)}</button>`).join("")}</div>` : "";

  $("labPanel").innerHTML = `
    <h2>${def.name}: ${esc(def.promise.charAt(0).toLowerCase() + def.promise.slice(1))}</h2>
    <p class="lab-story">${esc(def.story)}</p>
    <div class="lab-row">${modes}<button class="btn primary" id="labRun">${t === "durability" ? "Commit and read it back" : "Run experiment"}</button></div>
    <p class="lab-where">${esc(def.where)}</p>
    <div class="lab-out" id="labOut" aria-live="polite"></div>`;
}

$("labTabs").addEventListener("click", e => {
  const b = e.target.closest("[data-tab]"); if (!b || state.lab.running) return;
  state.lab.tab = b.dataset.tab;
  renderLab();
});

$("labPanel").addEventListener("click", e => {
  const m = e.target.closest("[data-mode]");
  if (m && !state.lab.running) {
    state.lab.mode[state.lab.tab] = m.dataset.mode;
    document.querySelectorAll("#labModes button").forEach(x => x.classList.toggle("on", x === m));
    $("labOut").innerHTML = "";
    return;
  }
  if (e.target.closest("#labRun")) runLab();
  if (e.target.closest("#labCheck")) checkDurability();
});

async function runLab() {
  if (state.lab.running) return;
  const t = state.lab.tab, def = LAB[t];
  const btn = $("labRun"), out = $("labOut");
  state.lab.running = true;
  btn.disabled = true; btn.textContent = "Running...";
  out.innerHTML = '<div class="skeleton"></div>';
  try {
    const data = await def.call(state.lab.mode[t]);
    out.innerHTML = labResultHtml(t, data);
  } catch (err) {
    out.innerHTML = `<div class="verdict bad"><span class="mark">!</span><div><b>The experiment couldn't run</b><p>${esc(err.message)}</p></div></div>`;
  } finally {
    state.lab.running = false;
    btn.disabled = false; btn.textContent = t === "durability" ? "Commit and read it back" : "Run again";
  }
}

function labResultHtml(t, data) {
  const v = data.verdict, st = data.state || {};
  let chips = "";
  if (t === "atomicity" || t === "consistency") {
    chips = `<div class="kv"><span>Bookings saved <b>${st.bookings}</b></span><span>Seats booked <b>${st.booked_seats}</b></span>${st.wallet != null ? `<span>Priya's wallet <b>${money(st.wallet)}</b></span>` : ""}</div>`;
  } else if (t === "isolation") {
    const oc = Object.entries(st.outcomes || {}).map(([n, r]) => `<span>${esc(n)} <b>${esc(r)}</b></span>`).join("");
    chips = `<div class="kv"><span>Seat ${esc(st.seat)} <b>${esc(st.status)}${st.owner ? " by " + esc(st.owner) : ""}</b></span>${oc}</div>`;
  } else if (t === "durability") {
    chips = `<div class="kv"><span>Committed rows <b>${st.rows}</b></span><span>innodb_flush_log_at_trx_commit <b>${esc(st.flush_setting)}</b></span></div>
      <div class="lab-row" style="margin-top:12px"><button class="btn ghost" id="labCheck">Check after restart</button></div><div id="durCheck"></div>`;
  }
  const rules = data.rules ? `<div class="rules">${data.rules.map(r => `<div class="${r.ok ? "y" : "n"}">${esc(r.rule)}</div>`).join("")}</div>` : "";
  return `
    <div class="verdict ${v.ok ? "ok" : "bad"}"><span class="mark">${v.ok ? "\u2713" : "!"}</span><div><b>${esc(v.title)}</b><p>${esc(v.text)}</p></div></div>
    <h3 class="mini-h">What happened, step by step</h3>
    ${timelineHtml(data.steps)}
    <h3 class="mini-h">Database state afterwards (read through a new connection)</h3>
    ${chips}${rules}`;
}

async function checkDurability() {
  const box = $("durCheck");
  box.innerHTML = '<div class="skeleton" style="height:60px"></div>';
  try {
    const d = await api("/api/acid/durability/check");
    box.innerHTML = `<div class="verdict ${d.count ? "ok" : "bad"}" style="margin-top:12px"><span class="mark">${d.count ? "\u2713" : "!"}</span><div>
      <b>${d.count ? `${d.count} committed row(s) found` : "No rows found"}</b>
      <p>${d.rows.length ? esc(d.rows.map(r => r.note).slice(0, 3).join("  |  ")) : "Run the experiment first."} If you restarted MySQL since, this is the proof the data survived.</p></div></div>`;
  } catch (err) { box.innerHTML = `<p class="form-msg">${esc(err.message)}</p>`; }
}

/* ----------------------------- 7. my tickets ----------------------------- */

async function loadTickets() {
  if (!state.user) { openGate(); return; }
  go("tickets");
  $("ticketList").innerHTML = '<div class="skeleton"></div>';
  try {
    const rows = await api(`/api/users/${state.user.id}/bookings`);
    if (!rows.length) {
      $("ticketList").innerHTML = '<div class="empty"><h3>No tickets yet</h3><p>Find a cinema near you and your tickets will show up here.</p><button class="btn primary" id="emptyFind">Find cinemas</button></div>';
      return;
    }
    const groups = new Map();
    rows.forEach(b => {
      const key = b.group_order_id ?? `single_${b.booking_id}`;
      if (!groups.has(key)) groups.set(key, { ...b, seats: [], total: 0 });
      const g = groups.get(key);
      g.seats.push(b.seat_no);
      g.total += Number(b.amount || 0);
    });
    $("ticketList").innerHTML = [...groups.entries()].map(([key, g]) => bigTicketHtml({
      ref: "CS" + String(typeof key === "number" ? key : g.booking_id).padStart(5, "0"),
      title: g.movie_title, cinema: g.theatre_name,
      when: `${dayWord(dayKey(g.show_time))}, ${fmtTime(g.show_time)}`,
      seats: g.seats.join(", "), amount: g.total, state: g.state,
      past: new Date(g.show_time) < new Date(),
    }, true)).join("");
  } catch (err) { $("ticketList").innerHTML = `<div class="empty"><h3>Couldn't load tickets</h3><p>${esc(err.message)}</p></div>`; }
}
$("ticketList").addEventListener("click", e => { if (e.target.closest("#emptyFind")) openDiscover(); });

/* ----------------------------- 8. live chat (Socket.IO) ----------------------------- */

function ensureSocket() {
  if (state.socket) return;
  if (typeof io === "undefined") return;     // Socket.IO CDN script didn't load: chat is disabled, booking still works
  state.socket = io(API_BASE);
  state.socket.on("connect", () => {
    $("liveDot").classList.add("on"); $("liveDot").title = "Live";
    if (state.chatMovie) state.socket.emit("join_movie", { movie_id: state.chatMovie });   // rooms are lost on reconnect
  });
  state.socket.on("disconnect", () => { $("liveDot").classList.remove("on"); $("liveDot").title = "Disconnected"; });
  state.socket.on("new_message", msg => {
    // we may still be subscribed to an older room for a moment; only show the open movie
    if (msg.movie_id === state.chatMovie) appendMessage(msg);
  });
}

async function openChat() {
  if (!state.user) { openGate(); return; }
  go("chat");
  renderStars();
  if (!state.movies.length) {
    try { state.movies = await api("/api/movies"); }
    catch (err) { $("chatFeed").innerHTML = `<p class="chat-empty">Couldn't load movies: ${esc(err.message)}</p>`; return; }
  }
  selectChatMovie(state.chatMovie || state.movies[0].id);
}

function renderPills() {
  $("chatMovies").innerHTML = state.movies.map(m =>
    `<button class="chip ${m.id === state.chatMovie ? "on" : ""}" data-id="${m.id}" aria-pressed="${m.id === state.chatMovie}">${esc(m.title)}</button>`).join("");
}
$("chatMovies").addEventListener("click", e => { const b = e.target.closest("[data-id]"); if (b) selectChatMovie(+b.dataset.id); });

async function selectChatMovie(id) {
  if (state.chatMovie && state.chatMovie !== id && state.socket) state.socket.emit("leave_movie", { movie_id: state.chatMovie });
  state.chatMovie = id;
  renderPills();
  if (state.socket) state.socket.emit("join_movie", { movie_id: id });
  $("chatFeed").innerHTML = "";
  try {
    const reviews = await api(`/api/movies/${id}/reviews`);
    if (id !== state.chatMovie) return;     // switched again while loading
    if (!reviews.length) $("chatFeed").innerHTML = '<p class="chat-empty">Nobody has said anything yet. Be the first.</p>';
    else reviews.forEach(r => appendMessage(r, true));
  } catch (err) { $("chatFeed").innerHTML = `<p class="chat-empty">${esc(err.message)}</p>`; }
}

function appendMessage(m, quiet) {
  const feed = $("chatFeed");
  const empty = feed.querySelector(".chat-empty"); if (empty) empty.remove();
  const mine = m.user_name === state.user.name;
  const hue = hueFor(m.user_name);
  const stars = "\u2605".repeat(m.rating) + "\u2606".repeat(5 - m.rating);
  feed.insertAdjacentHTML("beforeend", `<div class="msg ${mine ? "mine" : ""}">
    <div class="avatar" style="background:hsl(${hue} 70% 72%)">${esc(initials(m.user_name))}</div>
    <div class="bubble"><div class="who"><span>${esc(m.user_name)}</span><span class="st">${stars}</span></div><p>${esc(m.comment)}</p></div></div>`);
  feed.scrollTop = feed.scrollHeight;
}

function renderStars() {
  $("chatStars").innerHTML = [1, 2, 3, 4, 5].map(n =>
    `<button class="${n <= state.chatRating ? "on" : ""}" data-n="${n}" role="radio" aria-checked="${n === state.chatRating}" aria-label="${n} star${n > 1 ? "s" : ""}">\u2605</button>`).join("");
}
$("chatStars").addEventListener("click", e => { const b = e.target.closest("[data-n]"); if (b) { state.chatRating = +b.dataset.n; renderStars(); } });

function sendChat() {
  const text = $("chatText").value.trim();
  if (!text || !state.chatMovie) return;
  if (!state.socket || !state.socket.connected) { toast("Not connected to live chat yet", "bad"); return; }
  state.socket.emit("send_message", { movie_id: state.chatMovie, user_id: state.user.id, user_name: state.user.name, rating: state.chatRating, comment: text });
  $("chatText").value = "";
}
$("chatSend").addEventListener("click", sendChat);
$("chatText").addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });

/* ----------------------------- start ----------------------------- */
initGate();
go("gate");

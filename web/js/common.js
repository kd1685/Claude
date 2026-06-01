// Shared helpers for the Kingdom 1685 site.

const PAGES = [
  ["index.html", "Dashboard"],
  ["kp.html", "Power & KP"],
  ["dead.html", "Dead Troops"],
  ["dkp.html", "KvK DKP"],
  ["rallies.html", "Rallies"],
  ["players.html", "Governors"],
  ["map.html", "Map"],
  ["control.html", "Control"],
  ["audit.html", "Audit"],
];

// Backend base URL (set in config.js). "" = same origin as this page.
const API_BASE = (window.API_BASE || "").replace(/\/$/, "");

async function api(path, opts) {
  const res = await fetch(API_BASE + path, { credentials: "include", ...opts });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

function post(path, data) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data || {}),
  });
}

// Compact number: 12.3M, 4.1B, etc.
function fmt(n) {
  if (n === null || n === undefined || n === "") return "—";
  n = Number(n);
  const abs = Math.abs(n);
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toLocaleString();
}

function gainCell(g) {
  if (g === null || g === undefined) return '<td class="num muted">—</td>';
  const cls = g >= 0 ? "gain-pos" : "gain-neg";
  const sign = g >= 0 ? "+" : "";
  return `<td class="num ${cls}">${sign}${fmt(g)}</td>`;
}

function todayISO() { return new Date().toISOString().slice(0, 10); }
function daysAgoISO(d) {
  const t = new Date(); t.setDate(t.getDate() - d);
  return t.toISOString().slice(0, 10);
}

function toast(msg) {
  let t = document.querySelector(".toast");
  if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2600);
}

// Show a single non-intrusive banner if the backend can't be reached (e.g. the
// Pages site is live but the tracker isn't online yet). Data appears once it is.
function backendOffline() {
  if (document.getElementById("offline-banner")) return;
  const b = document.createElement("div");
  b.id = "offline-banner";
  b.style.cssText = "background:#3a2a12;border-bottom:1px solid var(--gold-dim);" +
    "color:var(--gold);padding:9px 16px;text-align:center;font-size:13px";
  b.textContent = "⏳ Live data backend isn't connected yet — rankings will appear here once the kingdom tracker is online.";
  const hdr = document.querySelector("header.topbar");
  hdr ? hdr.insertAdjacentElement("afterend", b) : document.body.prepend(b);
}
window.addEventListener("unhandledrejection", (e) => {
  const m = (e.reason && e.reason.message) || "";
  if (m.includes("Failed to fetch") || m.startsWith("404") || m.includes("NetworkError"))
    backendOffline();
});

async function buildHeader(active) {
  const cfg = await api("/api/config").catch(() => ({ kingdom: "1685", control_backend: "?" }));
  const links = PAGES.map(([href, label]) =>
    `<a href="${href}" class="${href === active ? "active" : ""}">${label}</a>`).join("");
  document.body.insertAdjacentHTML("afterbegin", `
    <header class="topbar">
      <div class="brand">⚔ Kingdom <b>${cfg.kingdom}</b><small>Rise of Kingdoms command center</small></div>
      <nav class="links">${links}</nav>
      <div class="spacer"></div>
      <span id="backend-pill">control: ${cfg.control_backend}</span>
    </header>`);
}

// Populate a <select> with the dates that actually have data (plus today).
async function fillDateOptions(selectEl, { selectFirst = true } = {}) {
  const dates = await api("/api/stats/dates").catch(() => []);
  const all = dates.length ? dates : [todayISO()];
  selectEl.innerHTML = all.map(d => `<option value="${d}">${d}</option>`).join("");
  if (selectFirst) selectEl.value = all[0];
  return all;
}

let _charts = {};
function lineChart(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId);
  if (_charts[canvasId]) _charts[canvasId].destroy();
  _charts[canvasId] = new Chart(ctx, {
    type: "line",
    data: { labels, datasets: datasets.map(d => ({ tension: .3, borderWidth: 2, pointRadius: 0, ...d })) },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#8d9bbd" } } },
      scales: {
        x: { ticks: { color: "#8d9bbd", maxTicksLimit: 8 }, grid: { color: "#2b3756" } },
        y: { ticks: { color: "#8d9bbd", callback: v => fmt(v) }, grid: { color: "#2b3756" } },
      },
    },
  });
}

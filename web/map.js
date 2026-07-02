import Panzoom from '@panzoom/panzoom';
import Swal from 'sweetalert2';
import 'sweetalert2/dist/sweetalert2.min.css';
// Only latin + latin-ext subsets (latin-ext covers Polish ę/ł/ń/ó/ś/ź/ż); 800 = ExtraBold labels.
import '@fontsource/open-sans/latin-400.css';
import '@fontsource/open-sans/latin-600.css';
import '@fontsource/open-sans/latin-800.css';
import '@fontsource/open-sans/latin-ext-400.css';
import '@fontsource/open-sans/latin-ext-600.css';
import '@fontsource/open-sans/latin-ext-800.css';
import './map.css';

const SVG_URL = 'interactive_map.svg';
const SPACES_URL = 'spaces.json';
const EXHIBITORS_URL = 'wystawcy_auto.json';
const FOCUS_MAX = 2.5;   // how far a sidebar click is allowed to zoom in

const stage = document.getElementById('stage');
const listEl = document.getElementById('list');
let svgEl, panzoom, entries = [], listEntries = [];

const esc = s => (s || '').replace(/[&<>"]/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// --- join SVG labels to the wystawcy_auto.json directory ------------------
const norm = s => (s || '').toLowerCase().replace(/[^0-9a-ząćęłńóśźż]+/gi, '');
const clean = s => { s = (s == null ? '' : String(s)).trim(); return (s === 'nan' || s === 'None') ? '' : s; };

// wystawcy_auto.json is keyed by stall RANGE ("5-6") or by name, with rich rows
// {name, stall, description, logo_path, …}. The rest of the join wants a flat
// lookup by a single number (or name), so expand ranges and trim to what we read.
function stallKeys(stall) {
  const span = /^\s*(\d+)\s*-\s*(\d+)\s*$/.exec(stall || '');
  if (span) {
    const lo = +span[1], hi = +span[2], out = [];
    for (let n = lo; n <= hi; n++) out.push(String(n));
    return out.length ? out : [String(lo)];
  }
  if (/^\s*\d+\s*$/.test(stall || '')) return [stall.trim()];
  return [String(stall)];
}
function normalizeDirectory(raw) {
  const dir = {};
  for (const v of Object.values(raw || {})) {
    const entry = { name: clean(v.name), description: clean(v.description),
                    logo: clean(v.logo_path || v.logo), links: Array.isArray(v.links) ? v.links : [] };
    for (const k of stallKeys(v.stall)) dir[k] = entry;
  }
  return dir;
}

function infoFor(exhibitors, num) {
  const v = exhibitors[num];
  if (v == null) return {};
  return typeof v === 'object' ? v : { name: v };
}

function buildEntries(spaces, exhibitors) {
  const byName = {};  // normalized exhibitor name -> [numbers], for name-drawn stalls
  for (const [num, v] of Object.entries(exhibitors)) {
    const name = typeof v === 'object' ? v.name : v;
    (byName[norm(name)] ||= []).push(num);
  }
  return spaces.map(sp => {
    let numbers, info;
    if (sp.numeric) {
      numbers = sp.label.match(/\d+/g) || [];
      info = infoFor(exhibitors, numbers[0]);
    } else {
      numbers = byName[norm(sp.label)] || [];        // recover number(s) if known
      info = numbers.length ? infoFor(exhibitors, numbers[0]) : {};
    }
    return {
      id: sp.id,
      label: sp.label,
      numbers,
      name: info.name || (sp.numeric ? '' : sp.label),  // name-only stalls keep their drawn name
      description: info.description || '',
      logo: info.logo || '',
      links: info.links || [],
    };
  });
}

// --- detail modal (SweetAlert2) -------------------------------------------
function openModal(entry) {
  const subtitle = entry.numbers.length ? 'Stoisko ' + entry.numbers.join(', ') : '';
  const links = (entry.links || []).map(l =>
    `<a href="${esc(l.href)}" target="_blank" rel="noopener noreferrer" style="display:block;font-size:14px;color:#1c7ed6;text-decoration:none;margin-top:4px">${esc(l.label)}</a>`).join('');
  Swal.fire({
    title: entry.name || entry.label,
    html: (subtitle ? `<div style="color:#868e96;font-size:13px;margin-bottom:8px">${esc(subtitle)}</div>` : '') +
          (entry.description ? `<p style="font-size:15px;color:#495057">${esc(entry.description)}</p>` : '') +
          (links ? `<div style="margin-top:8px">${links}</div>` : ''),
    imageUrl: entry.logo || undefined,
    imageWidth: 200,
    imageAlt: entry.name || entry.label,
    confirmButtonText: 'Zamknij',
    confirmButtonColor: '#1c7ed6',
    heightAuto: false,   // keep body at height:100% so the full-height map doesn't jump
  });
}

// --- highlight / activate a stall -----------------------------------------
function highlight(el) {
  svgEl.querySelectorAll('.map-space.active').forEach(e => e.classList.remove('active'));
  el.classList.add('active');
}
function activate(el, entry) {
  highlight(el);
  openModal(entry);
}

// --- center & gently zoom a stall (sidebar click) -------------------------
function focus(entry) {
  const el = svgEl.querySelector('#' + CSS.escape(entry.id));
  if (!el) return;
  highlight(el);

  // gentle: keep current zoom if already zoomed, otherwise ease to ~1.8x, never past FOCUS_MAX
  const scale = Math.min(Math.max(panzoom.getScale(), 1.8), FOCUS_MAX);
  panzoom.zoom(scale, { animate: true });

  // after the new scale lays out, pan so the stall sits at the stage centre
  requestAnimationFrame(() => {
    const s = stage.getBoundingClientRect();
    const b = el.getBoundingClientRect();
    const dx = (s.left + s.width / 2) - (b.left + b.width / 2);
    const dy = (s.top + s.height / 2) - (b.top + b.height / 2);
    const pan = panzoom.getPan();
    panzoom.pan(pan.x + dx / scale, pan.y + dy / scale, { animate: true });
    openModal(entry);
  });
}

// --- sidebar / hamburger --------------------------------------------------
function closeNav() { document.body.classList.remove('nav-open'); }
document.getElementById('hamburger').onclick = () => document.body.classList.toggle('nav-open');
document.getElementById('backdrop').onclick = closeNav;

// Some zones are drawn as several squares sharing one name (e.g. GnŻ ×2). The map
// keeps every square clickable, but the sidebar lists each name once — clicking it
// focuses the first square. Numbered stalls differ by number so they stay distinct.
function dedupeForList(entries) {
  const seen = new Set(), out = [];
  for (const e of entries) {
    const key = norm(e.name || e.label) + '|' + e.numbers.join(',');
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(e);
  }
  return out;
}

function render(filter) {
  const q = norm(filter);
  listEl.innerHTML = '';
  let n = 0;
  for (const e of listEntries) {
    const hay = norm(e.label + ' ' + e.name + ' ' + e.numbers.join(' '));
    if (q && !hay.includes(q)) continue;
    const li = document.createElement('li');
    li.innerHTML = `<div class="name">${esc(e.name || e.label)}</div>` +
      `<div class="nr">${e.numbers.length ? 'nr ' + esc(e.numbers.join(', ')) : ''}</div>`;
    li.onclick = () => { closeNav(); focus(e); };
    listEl.appendChild(li);
    n++;
  }
  document.getElementById('count').textContent = n + ' / ' + listEntries.length;
}
document.getElementById('search').addEventListener('input', e => render(e.target.value));

// --- boot -----------------------------------------------------------------
function fail(msg) {
  stage.insertAdjacentHTML('afterbegin', `<div id="error">${msg}</div>`);
}

async function boot() {
  let svgText, spaces, exhibitors;
  try {
    [svgText, spaces, exhibitors] = await Promise.all([
      fetch(SVG_URL).then(r => r.text()),
      fetch(SPACES_URL).then(r => r.json()),
      fetch(EXHIBITORS_URL).then(r => r.ok ? r.json() : {}).catch(() => ({})),
    ]);
  } catch (e) {
    fail(`Could not load <code>${SVG_URL}</code> / <code>${SPACES_URL}</code>.<br>` +
         `Browsers block <code>fetch()</code> over <code>file://</code> — serve the build:` +
         `<br><br><code>python -m http.server -d dist</code><br>then open ` +
         `<code>http://localhost:8000/</code>`);
    return;
  }

  stage.insertAdjacentHTML('afterbegin', svgText);
  svgEl = stage.querySelector('svg');
  entries = buildEntries(spaces, normalizeDirectory(exhibitors));
  listEntries = dedupeForList(entries);
  const byId = Object.fromEntries(entries.map(e => [e.id, e]));

  panzoom = Panzoom(svgEl, {
    maxScale: 20, minScale: 1, contain: 'outside',
    animate: true, duration: 200,
  });
  stage.addEventListener('wheel', panzoom.zoomWithWheel);  // wheel zoom (desktop)

  // Tell a tap from a pan: track movement during the gesture (capture phase, so we see it
  // even though panzoom stops propagation of its own pointer events). A real drag sets
  // `didPan`, which suppresses the click below — so panning never opens a modal.
  const TAP_SLOP = 8;
  let downXY = null, didPan = false;
  stage.addEventListener('pointerdown', e => { downXY = { x: e.clientX, y: e.clientY }; didPan = false; }, true);
  stage.addEventListener('pointermove', e => {
    if (downXY && Math.hypot(e.clientX - downXY.x, e.clientY - downXY.y) > TAP_SLOP) didPan = true;
  }, true);

  // Native click still fires on the stall (panzoom passes clicks through) — desktop & tap.
  svgEl.querySelectorAll('.map-space').forEach(el => {
    el.addEventListener('click', ev => {
      ev.stopPropagation();
      if (didPan) return;                 // it was a pan, not a tap
      const e = byId[el.id];
      if (e) activate(el, e);
    });
  });

  document.getElementById('zin').onclick = () => panzoom.zoomIn();
  document.getElementById('zout').onclick = () => panzoom.zoomOut();
  document.getElementById('zreset').onclick = () => panzoom.reset();

  render('');
  preloadLogos(entries);
}

// Warm the browser cache with the logos so modals show them instantly — but only
// during idle time, one at a time, so it never blocks the map or the network.
function preloadLogos(entries) {
  const urls = [...new Set(entries.map(e => e.logo).filter(Boolean))];
  const idle = window.requestIdleCallback || (fn => setTimeout(fn, 200));
  let i = 0;
  (function next() {
    if (i >= urls.length) return;
    new Image().src = urls[i++];
    idle(next);
  })();
}

boot();

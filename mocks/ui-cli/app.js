/*
 * FDAI operator-console CLI - design mock (static, no deps).
 *
 * Plays a JARVIS-style streaming briefing: boot banner -> greeting -> throughput
 * chart drawn left-to-right -> tier bars filling -> branch (HIL approval cards or
 * an all-clear free-chat prompt). Everything here is synthetic and customer-
 * agnostic; the real console would stream the same shape from read-only
 * console-tool calls. Streaming is presentation only - never a judgment.
 */

// --- synthetic briefing data (mirrors the read-only console-tool payload) -----
const BRIEFING = {
  env: 'staging',
  operator: 'Alice',
  clock: '09:41 UTC',
  windowLabel: 'last 24h',
  events: 1204,
  autoResolved: 1201,
  rollbacks: 0,
  shadowCandidates: 6,
  overridesActive: 2,
  tiers: [
    { tier: 'T0', label: 'deterministic', pct: 74, cls: 'teal' },
    { tier: 'T1', label: 'similarity', pct: 18, cls: 'steel' },
    { tier: 'T2', label: 'reasoning', pct: 8, cls: 'plum' },
  ],
  // evt-per-5min buckets across the window (drives the streaming chart)
  throughput: [
    120, 140, 135, 160, 210, 260, 240, 300, 520, 610, 700, 900,
    1180, 1240, 980, 760, 540, 430, 360, 300, 280, 240, 200, 170,
  ],
  hil: [
    {
      cls: 'med', risk: 'MEDIUM', riskCls: 'terra',
      verb: 'approve', action: 'scale-memory', resource: 'payments-api',
      change: '512Mi -> 1Gi',
      why: 'OOMKilled x2 in 1h, correlated to inc_1204',
      tier: 'T1 similarity 0.91 -> inc_0847 (learned action reused)',
      safety: 'blast=1 pod - stop=cpu>80% - rollback=pr_revert',
      path: 'pr_native -> opens PR #inc1204-mem (not applied directly)',
      gate: 'needs 1 approver, must not be the actor  (you qualify)',
      simulate: 'whatif.apply(1Gi) -> predicted OK, no new policy violation',
      audit: 'evt_9f3c -> dec_5521',
      tags: ['approve'],
      irreversible: false,
    },
    {
      cls: 'high', risk: 'HIGH', riskCls: 'dusty',
      verb: 'approve', action: 'rotate-key', resource: 'kv-prod',
      change: 'rotate signing key',
      why: 'key-age > 90d (rule kv-014, MCSB)',
      tier: 'T0 policy match (deterministic)',
      safety: 'blast=1 key - stop=consumer-error>1% - rollback=state_forward_only  (irreversible)',
      path: 'pr_native -> opens PR #kv-rotate',
      gate: 'breakglass - quorum 2 - not-self',
      simulate: 'whatif.rotate() -> consumers support hot-reload',
      audit: 'evt_2210 -> dec_7781',
      tags: ['breakglass'],
      irreversible: true,
    },
    {
      cls: 'low', risk: 'LOW', riskCls: 'sage',
      verb: 'review', action: 'promote-rule', resource: 'disk-idle-30d',
      change: 'shadow -> enforce',
      why: 'shadow 30d: 41/41 correct, 0 policy-violation escapes',
      tier: 'T0 deterministic rule',
      safety: 'blast=cost rule - stop=any escape demotes - rollback=pr_revert',
      path: 'pr_native -> opens PR #promote-disk-idle',
      gate: 'needs 1 reviewer',
      simulate: 'replay 30d shadow set -> unchanged verdicts',
      audit: 'shadow_disk-idle-30d -> dec_9002',
      tags: ['read'],
      irreversible: false,
    },
  ],
  suggestions: [
    'why did payments-api restart?',
    'cost trend this week',
    "what's maturing in shadow?",
  ],
};

// --- tiny animation runtime ---------------------------------------------------
const screen = document.getElementById('screen');
const statusLeft = document.getElementById('status-left');
let SPEED = 1;
let runToken = 0; // cancels an in-flight run on replay

const sleep = (ms) => new Promise((r) => setTimeout(r, ms / SPEED));
const RAMP = ' \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588'; // ' ▁▂▃▄▅▆▇█'

function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}
function el(html) {
  const d = document.createElement('div');
  d.className = 'line';
  d.innerHTML = html;
  screen.appendChild(d);
  screen.scrollTop = screen.scrollHeight;
  return d;
}
function blank() { return el('&nbsp;'); }

// stream text into an element, char by char
async function type(node, text, cps = 48, token) {
  const speedCps = cps;
  for (let i = 0; i <= text.length; i++) {
    if (token !== runToken) return;
    node.innerHTML = esc(text.slice(0, i)) + '<span class="cursor"></span>';
    await sleep(1000 / speedCps);
  }
  node.innerHTML = esc(text);
}

// stream a "narrator" line prefixed with a glyph
async function narrate(text, token, cls = 'narr') {
  const node = el(`<span class="${cls}"><span class="glyph">\u25c7</span> </span>`);
  const span = document.createElement('span');
  node.querySelector('span').appendChild(span);
  for (let i = 0; i <= text.length; i++) {
    if (token !== runToken) return node;
    span.innerHTML = esc(text.slice(0, i)) + '<span class="cursor"></span>';
    await sleep(1000 / 52);
  }
  span.innerHTML = esc(text);
  return node;
}

// --- phases -------------------------------------------------------------------
async function phaseBoot(token) {
  el('<span class="banner">    /\\   ___  ___  ___         _   _      _</span>');
  el('<span class="banner">   /--\\  | |  | . || . | ___ | |_| | ___ | |_</span>');
  el('<span class="banner">  /    \\ |_|  |___||  _||_-_||  _  ||_ -||  _|   operator-console</span>');
  el('<span class="banner">                    |_|                       v0.0.1 - staging</span>');
  await sleep(500);
  blank();
}

async function phaseGreeting(token) {
  await narrate(
    `Good morning, ${BRIEFING.operator}. Systems nominal. Let me bring you up to speed on the ${BRIEFING.windowLabel}.`,
    token,
  );
  blank();
}

async function phaseChart(token) {
  await narrate('Event throughput:', token);
  const series = BRIEFING.throughput;
  const max = Math.max(...series);
  const H = 7; // rows
  const grid = el('<span class="dim"></span>');
  const pre = document.createElement('span');
  grid.innerHTML = '';
  grid.appendChild(pre);

  // reveal columns left-to-right
  for (let shown = 1; shown <= series.length; shown++) {
    if (token !== runToken) return;
    pre.innerHTML = renderChart(series.slice(0, shown), series.length, max, H);
    await sleep(48);
  }
  // sparkline flourish
  const spark = series.map((v) => RAMP[1 + Math.round((v / max) * (RAMP.length - 2))]).join('');
  el(`<span class="dim">  spark </span><span class="teal">${spark}</span><span class="dim">   peak ${max} evt/5m at 13:00</span>`);
  blank();
}

function renderChart(shownSeries, totalCols, max, H) {
  const heights = shownSeries.map((v) => Math.max(1, Math.round((v / max) * H)));
  let out = '';
  for (let row = H; row >= 1; row--) {
    let axis = row === H ? String(max).padStart(5) + ' \u2524'
             : row === 1 ? '    0 \u2524'
             : '      \u2502';
    let line = '';
    for (let c = 0; c < totalCols; c++) {
      if (c < heights.length) {
        line += heights[c] >= row ? '\u2588' : ' ';
      } else {
        line += ' ';
      }
    }
    out += `<span class="dim">${axis}</span><span class="teal">${line}</span>\n`;
  }
  out += '<span class="dim">      \u2514' + '\u2500'.repeat(totalCols) + '</span>\n';
  out += '<span class="dim">       00        06        12        18</span>';
  return out;
}

async function phaseTiers(token) {
  await narrate('Routing held deterministic-first, as designed:', token);
  const WIDTH = 22;
  const rows = BRIEFING.tiers.map((t) => {
    const node = el(
      `<span class="bars"><span class="bar-row">` +
      `<span class="bar-label">${t.tier} ${t.label}</span>` +
      `<span class="bar-fill ${t.cls}"></span>` +
      `<span class="bar-track"></span>` +
      `<span class="pct dim"></span>` +
      `</span></span>`,
    );
    return { t, fill: node.querySelector('.bar-fill'), track: node.querySelector('.bar-track'), pct: node.querySelector('.pct') };
  });

  // fill all bars together, frame by frame
  const maxCells = Math.round((Math.max(...BRIEFING.tiers.map((t) => t.pct)) / 100) * WIDTH);
  for (let step = 0; step <= maxCells; step++) {
    if (token !== runToken) return;
    for (const r of rows) {
      const cells = Math.round((r.t.pct / 100) * WIDTH);
      const on = Math.min(step, cells);
      r.fill.textContent = '\u2588'.repeat(on);
      r.track.textContent = '\u2591'.repeat(WIDTH - on);
      r.pct.textContent = `  ${String(r.t.pct).padStart(3)}%`;
    }
    await sleep(55);
  }
  blank();

  await narrate(
    `${BRIEFING.autoResolved} of ${BRIEFING.events} events auto-resolved. ` +
    `${BRIEFING.rollbacks} rollbacks. ${BRIEFING.shadowCandidates} shadow candidates maturing quietly.`,
    token,
  );
  const s = BRIEFING;
  el(
    `<div class="summary">` +
    `<span class="dim">events </span><span class="b">${s.events}</span>` +
    `<span class="dim">   auto </span><span class="sage b">${s.autoResolved}</span>` +
    `<span class="dim">   rollbacks </span><span class="sage b">${s.rollbacks}</span>` +
    `<span class="dim">   overrides </span><span class="b">${s.overridesActive}</span>` +
    `<span class="dim">   audit </span><span class="teal">healthy</span>` +
    `</div>`,
  );
  statusLeft.innerHTML =
    `T0 <span style="color:var(--teal)">74%</span>  ` +
    `T1 <span style="color:var(--steel)">18%</span>  ` +
    `T2 <span style="color:var(--plum)">8%</span>   ` +
    `<span>shadow-mode ON</span>`;
  blank();
}

function tagHtml(tags) {
  return tags.map((t) => `<span class="tag ${t}">[${t}]</span>`).join('');
}

async function phaseBranchHil(token) {
  await narrate(
    `Three items, however, I deferred to you - autonomy stops at your risk line.`,
    token,
  );
  blank();
  let i = 0;
  for (const item of BRIEFING.hil) {
    if (token !== runToken) return;
    i++;
    const irr = item.irreversible ? ' <span class="dusty b">irreversible</span>' : '';
    el(
      `<div class="card ${item.cls}">` +
      `<div class="hdr">` +
        `<span><span class="b">${i}/3 - ${item.action}</span> <span class="dim">- ${item.resource}</span></span>` +
        `<span class="${item.riskCls} b">${item.risk}</span>` +
      `</div>` +
      `<div><span class="dim">change   </span>${esc(item.change)}   ${tagHtml(item.tags)}</div>` +
      `<div><span class="dim">why      </span>${esc(item.why)}</div>` +
      `<div><span class="dim">tier     </span>${esc(item.tier)}</div>` +
      `<div><span class="dim">safety   </span>${esc(item.safety)}${irr}</div>` +
      `<div><span class="dim">path     </span>${esc(item.path)}</div>` +
      `<div><span class="dim">gate     </span>${esc(item.gate)}</div>` +
      `<div><span class="dim">simulate </span><span class="sage">\u2713</span> ${esc(item.simulate)}</div>` +
      `<div class="keys">` +
        `<span class="key a">a</span>approve \u2192 PR   ` +
        `<span class="key r">r</span>reject \u2192 no-op+audit   ` +
        `<span class="key w">w</span>why   ` +
        `<span class="key n">\u2192</span>next` +
      `</div>` +
      `<div class="dim" style="margin-top:6px">audit  ${esc(item.audit)}</div>` +
      `</div>`,
    );
    await sleep(650);
  }
  blank();
  const p = el('');
  p.innerHTML = `<span class="prompt-row"><span class="sig">\u203a</span> <span class="dim">press 1-3 to act, or type to ask the narrator</span> <span class="cursor"></span></span>`;
}

async function phaseBranchCalm(token) {
  await narrate(
    `Nothing needs your signature right now. Everything in range is handled and reversible.`,
    token,
  );
  blank();
  await narrate("Anything you'd like to look into? For example:", token);
  for (const s of BRIEFING.suggestions) {
    el(`<span class="dim">   \u2022 </span><span class="steel">"${esc(s)}"</span>`);
    await sleep(160);
  }
  blank();
  const p = el('');
  p.innerHTML =
    `<span class="prompt-row"><span class="sig">\u203a</span> <span class="cursor"></span></span>` +
    `<span class="dim">  (read-only by default - I'll ask before anything with a side effect)</span>`;
}

// --- orchestration ------------------------------------------------------------
async function run() {
  const token = ++runToken;
  screen.innerHTML = '';
  statusLeft.textContent = 'T0 -  T1 -  T2 -';
  await phaseBoot(token);
  await phaseGreeting(token);
  await phaseChart(token);
  await phaseTiers(token);
  if (MODE === 'hil') await phaseBranchHil(token);
  else await phaseBranchCalm(token);
}

// --- controls -----------------------------------------------------------------
let MODE = 'hil';
const modeBtn = document.getElementById('mode');
const speedBtn = document.getElementById('speed');
document.getElementById('replay').addEventListener('click', run);
modeBtn.addEventListener('click', () => {
  MODE = MODE === 'hil' ? 'calm' : 'hil';
  modeBtn.textContent = MODE === 'hil' ? 'branch: HIL' : 'branch: calm';
  modeBtn.classList.toggle('on', MODE === 'hil');
  run();
});
const SPEEDS = [1, 2, 4, 0.5];
let speedIdx = 0;
speedBtn.addEventListener('click', () => {
  speedIdx = (speedIdx + 1) % SPEEDS.length;
  SPEED = SPEEDS[speedIdx];
  speedBtn.textContent = `speed: ${SPEED}x`;
});

run();

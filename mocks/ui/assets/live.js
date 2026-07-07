// Calm Slate - Live cockpit for the FDAI operator console mock.
// Synthesizes control-plane events (T0/T1/T2 -> gate -> executor -> audit) and
// renders them as an activity swarm. Nothing here calls a real backend; the
// production console will bind the same DOM structure to a read-only event feed.
//
// Distribution deliberately matches the roadmap: T0 dominates (~75%), T1 mid
// (~18%), T2 minority (~7%). Gate outcomes follow the risk model: T2 escalates
// to HIL / abstain far more often than T0.

(function () {
  "use strict";

  // ---------- config ----------
  var TIER_WEIGHTS = { t0: 0.75, t1: 0.18, t2: 0.07 };
  var GATE_MIX = {
    t0: { auto: 0.92, hil: 0.03, abstain: 0.01, deny: 0.04 },
    t1: { auto: 0.83, hil: 0.10, abstain: 0.04, deny: 0.03 },
    t2: { auto: 0.35, hil: 0.42, abstain: 0.18, deny: 0.05 }
  };
  var STAGES = ["route", "verify", "gate", "execute"];
  // Per-tier total pipeline duration (ms). Randomised +/-25% per event.
  var TIER_TOTAL_MS = { t0: 320, t1: 750, t2: 2100 };
  var BASE_RATE = 22; // events / sec at Rate 1x
  var FADE_1_MS = 900;
  var FADE_2_MS = 1600;
  var RETIRE_MS = 2400;
  var TICKER_MAX = 8;
  var SPARK_BUCKETS = 60; // one second per bucket
  var SPARK_BUCKET_MS = 1000;

  var CATALOG = [
    { rule: "storage.public-blob.deny",           at: "storage.public-blob.disable",       scope: "rg-webapp",   vertical: "change"     },
    { rule: "database.pitr.required",             at: "database.enable-pitr",              scope: "rg-billing",  vertical: "resilience" },
    { rule: "compute.autoscale.floor.min-2",      at: "compute.autoscale.raise-floor",     scope: "rg-web-eu",   vertical: "change"     },
    { rule: "identity.cert.expiry.30d",           at: "identity.cert.rotate",              scope: "rg-core",     vertical: "change"     },
    { rule: "cost.rightsize.candidate",           at: "cost.rightsize.downshift-cpu",      scope: "rg-batch",    vertical: "cost"       },
    { rule: "network.firewall.orphan-rule",       at: "network.firewall.deny-orphan",      scope: "rg-net",      vertical: "change"     },
    { rule: "k8s.rbac.cluster-admin.narrow",      at: "k8s.rbac.narrow-cluster-admin",     scope: "aks-prod",    vertical: "change"     },
    { rule: "network.dns.public-resolver.deny",   at: "network.dns.pin-internal",          scope: "rg-net",      vertical: "change"     },
    { rule: "keyvault.access.grant-narrow",       at: "keyvault.grant-narrow",             scope: "rg-ident",    vertical: "change"     },
    { rule: "observability.log.retention",        at: "observability.log.extend-retention", scope: "rg-obs",     vertical: "change"     },
    { rule: "cost.orphan-disk.cleanup",           at: "cost.disk.delete-orphan",           scope: "rg-legacy",   vertical: "cost"       },
    { rule: "reliability.replica-lag.alert",      at: "reliability.replica.failover",      scope: "rg-db-eu",    vertical: "resilience" },
    { rule: "storage.tls.min-1_2",                at: "storage.tls.enforce-min-1_2",       scope: "rg-media",    vertical: "change"     },
    { rule: "compute.public-ip.deny",             at: "compute.public-ip.remove",          scope: "rg-net",      vertical: "change"     },
    { rule: "cost.reserved-instance.recommend",   at: "cost.ri.propose-purchase",          scope: "rg-fleet",    vertical: "cost"       },
    { rule: "reliability.backup.stale",           at: "reliability.backup.trigger",        scope: "rg-billing",  vertical: "resilience" },
    { rule: "network.nsg.overly-permissive",      at: "network.nsg.narrow-source",         scope: "rg-web-us",   vertical: "change"     },
    { rule: "identity.mi.unused",                 at: "identity.mi.retire",                scope: "rg-core",     vertical: "change"     }
  ];

  // ---------- state ----------
  var swarm = document.getElementById("swarm");
  var ticker = document.getElementById("ticker");
  var pauseBtn = document.getElementById("live-pause");
  var rateBtn = document.getElementById("live-rate");
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var pool = []; // tile records: { el, ev, startedAt, endsAt, retiresAt, state }
  var lastFrame = 0;
  var emitAccum = 0;
  var paused = false;
  var speed = 1;
  var running = true;

  // Sliding buckets for the last 60s
  var buckets = []; // each: { t0, t1, t2, auto, hil, abstain, deny }
  for (var i = 0; i < SPARK_BUCKETS; i++) buckets.push(zeroBucket());
  var lastBucketAt = performance.now();

  // ---------- helpers ----------
  function zeroBucket() { return { t0: 0, t1: 0, t2: 0, total: 0, auto: 0, hil: 0, abstain: 0, deny: 0 }; }
  function rng() { return Math.random(); }
  function pick(arr) { return arr[Math.floor(rng() * arr.length)]; }
  function weightedTier() {
    var r = rng();
    if (r < TIER_WEIGHTS.t0) return "t0";
    if (r < TIER_WEIGHTS.t0 + TIER_WEIGHTS.t1) return "t1";
    return "t2";
  }
  function weightedOutcome(tier) {
    var m = GATE_MIX[tier];
    var r = rng();
    var acc = 0;
    var keys = ["auto", "hil", "abstain", "deny"];
    for (var i = 0; i < keys.length; i++) {
      acc += m[keys[i]];
      if (r < acc) return keys[i];
    }
    return "auto";
  }
  function shortId() {
    var s = Math.floor(rng() * 0xFFFFFF).toString(16).padStart(6, "0");
    return "evt-" + s;
  }
  function pad2(n) { return n < 10 ? "0" + n : "" + n; }
  function pad3(n) { return n < 10 ? "00" + n : n < 100 ? "0" + n : "" + n; }
  function timeStr(d) { return pad2(d.getUTCHours()) + ":" + pad2(d.getUTCMinutes()) + ":" + pad2(d.getUTCSeconds()) + "." + pad3(d.getUTCMilliseconds()); }

  // ---------- pool creation ----------
  function computePoolSize() {
    // Fit whatever the grid gives us; keep at least 42, at most 140.
    var probe = document.createElement("div");
    probe.className = "cs-tile";
    probe.style.visibility = "hidden";
    swarm.appendChild(probe);
    var w = probe.offsetWidth || 152;
    swarm.removeChild(probe);
    var cols = Math.max(4, Math.floor(swarm.clientWidth / (w + 8)));
    var rows = 10;
    return Math.max(42, Math.min(140, cols * rows));
  }

  function buildTile() {
    var el = document.createElement("div");
    el.className = "cs-tile";
    el.setAttribute("data-empty", "true");
    el.innerHTML = ''
      + '<div class="cs-tile-inner">'
      +   '<div class="cs-tile-top">'
      +     '<span class="cs-tile-tier"></span>'
      +     '<span class="cs-tile-stage"></span>'
      +   '</div>'
      +   '<div class="cs-tile-title"></div>'
      +   '<div class="cs-tile-meta">'
      +     '<span class="cs-tile-scope"></span>'
      +     '<span class="cs-tile-id"></span>'
      +   '</div>'
      + '</div>'
      + '<div class="cs-tile-bar"><span></span></div>';
    return {
      el: el,
      tierEl: el.querySelector(".cs-tile-tier"),
      stageEl: el.querySelector(".cs-tile-stage"),
      titleEl: el.querySelector(".cs-tile-title"),
      scopeEl: el.querySelector(".cs-tile-scope"),
      idEl: el.querySelector(".cs-tile-id"),
      barEl: el.querySelector(".cs-tile-bar > span"),
      ev: null,
      startedAt: 0,
      endsAt: 0,
      retiresAt: 0,
      state: "empty"
    };
  }

  function initPool() {
    swarm.innerHTML = "";
    pool.length = 0;
    var n = computePoolSize();
    for (var i = 0; i < n; i++) {
      var t = buildTile();
      pool.push(t);
      swarm.appendChild(t.el);
    }
  }

  // ---------- lifecycle ----------
  function pickSlot() {
    // Only recycle fully-retired slots. If the swarm is at capacity, drop the
    // new event - realistic backpressure signal beats popping a mid-fade tile.
    for (var i = 0; i < pool.length; i++) {
      if (pool[i].state === "empty") return pool[i];
    }
    return null;
  }

  function spawn(now) {
    var slot = pickSlot();
    if (!slot) return; // fully busy - drop; the swarm is at capacity
    var tier = weightedTier();
    var jitter = 0.75 + rng() * 0.5; // 75%..125%
    var total = Math.round(TIER_TOTAL_MS[tier] * jitter);
    var outcome = weightedOutcome(tier);
    var sample = pick(CATALOG);
    var id = shortId();

    slot.ev = { tier: tier, outcome: outcome, sample: sample, id: id, total: total, emitAt: Date.now() };
    slot.startedAt = now;
    slot.endsAt = now + total;
    slot.retiresAt = 0;
    slot.state = "active";

    var el = slot.el;
    el.setAttribute("data-empty", "false");
    el.setAttribute("data-tier", tier);
    el.setAttribute("data-state", "active");
    el.setAttribute("data-outcome", outcome);
    el.removeAttribute("data-fade");
    slot.tierEl.className = "cs-tile-tier " + tier;
    slot.tierEl.textContent = tier.toUpperCase();
    slot.stageEl.textContent = STAGES[0];
    slot.titleEl.textContent = sample.at;
    slot.titleEl.title = sample.rule + " -> " + sample.at;
    slot.scopeEl.textContent = sample.scope;
    slot.idEl.textContent = id;
    slot.barEl.style.width = "0%";

    if (reduced) {
      // Skip animation - jump to done state visually
      finish(slot, now);
    }

    countInBucket(now, tier);
  }

  function stageIndex(elapsedRatio) {
    // 0..0.35 route, 0.35..0.60 verify, 0.60..0.80 gate, 0.80..1.0 execute
    if (elapsedRatio < 0.35) return 0;
    if (elapsedRatio < 0.60) return 1;
    if (elapsedRatio < 0.80) return 2;
    return 3;
  }

  function finish(slot, now) {
    slot.state = "done";
    slot.retiresAt = now + RETIRE_MS;
    slot.el.setAttribute("data-state", "done");
    slot.barEl.style.width = "100%";
    // Human-facing stage label reflects the outcome
    var terminalLabel = slot.ev.outcome === "auto" ? "auto" : slot.ev.outcome;
    slot.stageEl.textContent = terminalLabel;

    // Emit audit + count outcome in bucket
    countOutcomeInBucket(now, slot.ev.outcome);
    pushTicker(slot);
  }

  function retire(slot) {
    slot.state = "empty";
    slot.ev = null;
    slot.el.setAttribute("data-empty", "true");
    slot.el.removeAttribute("data-state");
    slot.el.removeAttribute("data-outcome");
    slot.el.removeAttribute("data-tier");
    slot.el.removeAttribute("data-fade");
  }

  function tick(now) {
    if (running) {
      if (!lastFrame) lastFrame = now;
      var dt = Math.min(200, now - lastFrame);
      lastFrame = now;

      if (!paused) {
        var rate = BASE_RATE * speed;
        emitAccum += (dt / 1000) * rate;
        while (emitAccum >= 1) { spawn(now); emitAccum -= 1; }
      }

      // Advance tiles
      for (var i = 0; i < pool.length; i++) {
        var t = pool[i];
        if (t.state === "active") {
          var elapsed = now - t.startedAt;
          var total = t.endsAt - t.startedAt;
          var ratio = Math.min(1, elapsed / total);
          t.barEl.style.width = (ratio * 100).toFixed(1) + "%";
          var s = stageIndex(ratio);
          if (t.stageEl.textContent !== STAGES[s]) t.stageEl.textContent = STAGES[s];
          if (elapsed >= total) finish(t, now);
        } else if (t.state === "done") {
          var age = now - t.endsAt;
          if (age > FADE_2_MS) {
            if (t.el.getAttribute("data-fade") !== "2") t.el.setAttribute("data-fade", "2");
          } else if (age > FADE_1_MS) {
            if (t.el.getAttribute("data-fade") !== "1") t.el.setAttribute("data-fade", "1");
          }
          if (now >= t.retiresAt) retire(t);
        }
      }

      // Slide sparkline buckets every second
      if (now - lastBucketAt >= SPARK_BUCKET_MS) {
        while (now - lastBucketAt >= SPARK_BUCKET_MS) {
          buckets.shift();
          buckets.push(zeroBucket());
          lastBucketAt += SPARK_BUCKET_MS;
        }
        renderKpis();
        renderSparkline();
      }
    }
    requestAnimationFrame(tick);
  }

  // ---------- ticker ----------
  var tickerCount = 0;
  function pushTicker(slot) {
    var li = document.createElement("li");
    var d = new Date();
    var tspan = '<span class="t">' + timeStr(d) + '</span>';
    var tier = slot.ev.tier;
    var tierHtml = '<span class="cs-tier ' + tier + ' tier">' + tier.toUpperCase() + '</span>';
    var idHtml = '<span class="t">' + slot.ev.id + '</span>';
    var ruleHtml = '<span class="rule">' + slot.ev.sample.rule + ' -&gt; ' + slot.ev.sample.at + '</span>';
    var outHtml = '<span class="out ' + slot.ev.outcome + '">' + slot.ev.outcome + '</span>';
    li.innerHTML = tspan + tierHtml + idHtml + ruleHtml + outHtml;
    ticker.insertBefore(li, ticker.firstChild);
    tickerCount++;
    while (ticker.children.length > TICKER_MAX) ticker.removeChild(ticker.lastChild);
  }

  // ---------- buckets ----------
  function countInBucket(now, tier) {
    var b = buckets[buckets.length - 1];
    b[tier]++;
    b.total++;
  }
  function countOutcomeInBucket(now, outcome) {
    var b = buckets[buckets.length - 1];
    b[outcome]++;
  }
  function windowTotals() {
    var t = { t0: 0, t1: 0, t2: 0, total: 0, auto: 0, hil: 0, abstain: 0, deny: 0 };
    for (var i = 0; i < buckets.length; i++) {
      var b = buckets[i];
      t.t0 += b.t0; t.t1 += b.t1; t.t2 += b.t2; t.total += b.total;
      t.auto += b.auto; t.hil += b.hil; t.abstain += b.abstain; t.deny += b.deny;
    }
    return t;
  }
  function pct(n, d) { return d > 0 ? Math.round((n / d) * 100) : 0; }

  // ---------- render KPIs ----------
  var kEps = document.getElementById("k-eps");
  var kAuto = document.getElementById("k-auto");
  var kT0 = document.getElementById("k-t0");
  var kT1 = document.getElementById("k-t1");
  var kT2 = document.getElementById("k-t2");
  var mixBar = document.getElementById("k-mix");
  var tierBar = document.getElementById("k-tier");

  function renderKpis() {
    var t = windowTotals();
    var eps = (t.total / SPARK_BUCKETS).toFixed(1);
    kEps.firstChild.nodeValue = eps;
    var outcomeTotal = t.auto + t.hil + t.abstain + t.deny;
    kAuto.textContent = pct(t.auto, outcomeTotal) + "%";
    kT0.textContent = "T0 " + pct(t.t0, t.total) + "%";
    kT1.textContent = "T1 " + pct(t.t1, t.total) + "%";
    kT2.textContent = "T2 " + pct(t.t2, t.total) + "%";
    // Stacked bars
    var mixSpans = mixBar.children;
    mixSpans[0].style.width = pct(t.auto, outcomeTotal) + "%";
    mixSpans[1].style.width = pct(t.hil, outcomeTotal) + "%";
    mixSpans[2].style.width = pct(t.abstain, outcomeTotal) + "%";
    mixSpans[3].style.width = pct(t.deny, outcomeTotal) + "%";
    var tierSpans = tierBar.children;
    tierSpans[0].style.width = pct(t.t0, t.total) + "%";
    tierSpans[1].style.width = pct(t.t1, t.total) + "%";
    tierSpans[2].style.width = pct(t.t2, t.total) + "%";
  }

  // ---------- sparkline ----------
  var spark = document.querySelector('canvas[data-spark="eps"]');
  var sparkCtx = spark ? spark.getContext("2d") : null;

  function readColor(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  var COL = {
    t0: readColor("--cs-sage")   || "#5E8259",
    t1: readColor("--cs-teal")   || "#4F847E",
    t2: readColor("--cs-plum")   || "#7B6C9C",
    hairline: readColor("--cs-hairline") || "#E3E1DE"
  };

  function resizeSpark() {
    if (!spark) return;
    var dpr = window.devicePixelRatio || 1;
    var w = spark.clientWidth;
    var h = spark.clientHeight;
    spark.width = Math.round(w * dpr);
    spark.height = Math.round(h * dpr);
    sparkCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function renderSparkline() {
    if (!sparkCtx) return;
    var w = spark.clientWidth;
    var h = spark.clientHeight;
    sparkCtx.clearRect(0, 0, w, h);
    // Baseline
    sparkCtx.strokeStyle = COL.hairline;
    sparkCtx.lineWidth = 1;
    sparkCtx.beginPath();
    sparkCtx.moveTo(0, h - 0.5);
    sparkCtx.lineTo(w, h - 0.5);
    sparkCtx.stroke();

    var n = buckets.length;
    var max = 1;
    for (var i = 0; i < n; i++) if (buckets[i].total > max) max = buckets[i].total;
    var stepX = w / (n - 1);

    function drawSeries(field, color) {
      sparkCtx.strokeStyle = color;
      sparkCtx.lineWidth = 1.4;
      sparkCtx.beginPath();
      for (var i = 0; i < n; i++) {
        var v = buckets[i][field];
        var x = i * stepX;
        var y = h - (v / max) * (h - 2) - 1;
        if (i === 0) sparkCtx.moveTo(x, y); else sparkCtx.lineTo(x, y);
      }
      sparkCtx.stroke();
    }
    drawSeries("t0", COL.t0);
    drawSeries("t1", COL.t1);
    drawSeries("t2", COL.t2);
  }

  // ---------- controls ----------
  pauseBtn.addEventListener("click", function () {
    paused = !paused;
    pauseBtn.textContent = paused ? "Resume" : "Pause";
    pauseBtn.setAttribute("aria-pressed", paused ? "true" : "false");
    document.querySelector(".cs-live-heartbeat").style.animationPlayState = paused ? "paused" : "";
  });
  rateBtn.addEventListener("click", function () {
    var order = [1, 2, 4, 0.5];
    var idx = order.indexOf(speed);
    speed = order[(idx + 1) % order.length];
    rateBtn.textContent = "Rate: " + speed + "x";
  });

  window.addEventListener("resize", function () {
    resizeSpark();
    // If pool size changed materially, rebuild.
    var expected = computePoolSize();
    if (Math.abs(expected - pool.length) > 8) initPool();
  });

  // ---------- boot ----------
  initPool();
  // Wait one frame so layout has settled before sizing the canvas.
  requestAnimationFrame(function (t) {
    resizeSpark();
    lastFrame = t;
    lastBucketAt = t;
    renderSparkline();
    requestAnimationFrame(tick);
  });

  // Prime a few seconds of history so the sparkline is not empty at load
  (function prime() {
    var now = performance.now();
    for (var i = 0; i < 60; i++) {
      var b = buckets[i];
      // low-baseline synthetic history for visual continuity
      for (var k = 0; k < BASE_RATE; k++) {
        var tier = weightedTier();
        b[tier]++;
        b.total++;
        var out = weightedOutcome(tier);
        b[out]++;
      }
    }
    renderKpis();
    renderSparkline();
  }());
})();

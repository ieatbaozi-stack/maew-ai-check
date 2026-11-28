(() => {
  const PET_WHISPERS = ["purr~", "meow~", "mrrp~", "nap time?", "♥"];
  const ACTIVE_STEPS = [1, 2, 3, 5, 10, 15, 30, 60];
  const IDLE_STEPS = [15, 30, 45, 60, 90, 120, 180];

  const LOCK_SVG = `<svg class="lock-svg" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.2" y="5.5" width="7.6" height="5" rx="1.2"/><path d="M4 5.5V4a2 2 0 0 1 4 0v1.5"/></svg>`;

  const PROVIDER_CATALOG = [
    { id: "claude_web", short: "CL", name: "Claude.ai", subtitle: "5h / 7d web quota", auth: "web" },
    { id: "claude_code", short: "CC", name: "Claude Code logs", subtitle: "Offline ~/.claude drawer", auth: "local" },
    { id: "antigravity", short: "AG", name: "Antigravity", subtitle: "Local agy CLI quota", auth: "cli" },
    { id: "codex", short: "CX", name: "Codex", subtitle: "ChatGPT 5h / 7d quota", auth: "web" },
    { id: "copilot", short: "CP", name: "GitHub Copilot", subtitle: "Monthly credits via PAT", auth: "key", secretKey: "github_pat", placeholder: "github_pat_..." },
    { id: "openrouter", short: "OR", name: "OpenRouter", subtitle: "Daily spend & credits", auth: "key", secretKey: "openrouter_key", placeholder: "sk-or-v1-..." },
    { id: "opencode_go", short: "OC", name: "OpenCode Go", subtitle: "5h / 7d / 30d quota", auth: "key", secretKey: "opencode_go_key", placeholder: "oc_sk_..." },
    { id: "minimax", short: "MM", name: "MiniMax", subtitle: "Coding Plan 5h / 7d", auth: "key", secretKey: "minimax_key", placeholder: "sk-cp-..." },
  ];

  const COMPACT_ORDER = [
    ["claude_web", "CL"],
    ["antigravity", "AG"],
    ["codex", "CX"],
    ["copilot", "CP"],
    ["openrouter", "OR"],
    ["opencode_go", "OC"],
    ["minimax", "MM"],
  ];

  const state = {
    config: null,
    savedKeys: {},
    scanResults: {},
    snapshots: {},
    refreshing: false,
    view: "dashboard",
    skin: "orange",
    theme: "dark",
    alwaysOnTop: true,
    activeMin: 5,
    idleMin: 60,
    providers: {
      claude_web: true,
      claude_code: true,
      antigravity: true,
      codex: false,
      copilot: false,
      openrouter: false,
      opencode_go: false,
      minimax: false,
      copilot_monthly_quota: 1500,
      openrouter_daily_budget: null,
      minimax_region: "international",
    },
    mood: "sleep",
    frame: 0,
    showHeart: false,
    heartTimer: null,
    localDrawerOpen: false,
  };

  const els = {
    brandCat: document.getElementById("brandCat"),
    btnCompact: document.getElementById("btnCompact"),
    btnRefresh: document.getElementById("btnRefresh"),
    btnPin: document.getElementById("btnPin"),
    btnSettings: document.getElementById("btnSettings"),
    btnHide: document.getElementById("btnHide"),
    catPetArea: document.getElementById("catPetArea"),
    catCanvas: document.getElementById("catCanvas"),
    petWhisper: document.getElementById("petWhisper"),
    shelfState: document.getElementById("shelfState"),
    shelfSub: document.getElementById("shelfSub"),
    compactReadout: document.getElementById("compactReadout"),
    dashboardView: document.getElementById("dashboardView"),
    settingsView: document.getElementById("settingsView"),
    providersContainer: document.getElementById("providersContainer"),
    skinGrid: document.getElementById("skinGrid"),
    btnBackDash: document.getElementById("btnBackDash"),
    themeDark: document.getElementById("themeDark"),
    themeLight: document.getElementById("themeLight"),
    activeDec: document.getElementById("activeDec"),
    activeInc: document.getElementById("activeInc"),
    activeVal: document.getElementById("activeVal"),
    idleDec: document.getElementById("idleDec"),
    idleInc: document.getElementById("idleInc"),
    idleVal: document.getElementById("idleVal"),
    btnScanProviders: document.getElementById("btnScanProviders"),
    providersSettingsList: document.getElementById("providersSettingsList"),
    btnSaveSettings: document.getElementById("btnSaveSettings"),
    footerUpdated: document.getElementById("footerUpdated"),
    footerNext: document.getElementById("footerNext"),
  };

  function api() {
    return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
  }

  function escapeHtml(text) {
    return String(text ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function severityKey(pct) {
    if (pct === null || pct === undefined) return "low";
    if (pct >= 95) return "crit";
    if (pct >= 80) return "high";
    if (pct >= 60) return "mid";
    return "low";
  }

  function formatReset(isoStr, resetLabel) {
    if (resetLabel) return resetLabel;
    if (!isoStr) return "";
    const target = new Date(isoStr);
    const diffMs = target.getTime() - Date.now();
    if (Number.isNaN(diffMs) || diffMs <= 0) return "soon";
    const totalMin = Math.floor(diffMs / 60000);
    const days = Math.floor(totalMin / 1440);
    const hours = Math.floor((totalMin % 1440) / 60);
    const mins = totalMin % 60;
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
  }

  function isWeeklyMetric(m) {
    if (!m) return false;
    const lbl = String(m.label || "").toLowerCase();
    return lbl === "7d" || lbl === "weekly" || m.window_hours === 168;
  }

  function isSession5hMetric(m) {
    if (!m) return false;
    const lbl = String(m.label || "").toLowerCase();
    return lbl === "5h" || m.window_hours === 5;
  }

  function isAtLimit(m) {
    return m && typeof m.percent_used === "number" && m.percent_used >= 99.5;
  }

  function groupWeeklyCapped(metrics) {
    return (metrics || []).some((m) => isWeeklyMetric(m) && isAtLimit(m));
  }

  function extractCompactSummary(snap) {
    if (!snap || snap.status !== "ok") return null;
    const metrics = snap.metrics || [];
    const byGroup = new Map();
    for (const m of metrics) {
      const g = m.group || "";
      if (!byGroup.has(g)) byGroup.set(g, []);
      byGroup.get(g).push(m);
    }

    // Standard rule: ALWAYS report 5h session % for 5h/7d providers;
    // prioritize any locked group (7d or 5h at 100%) so compact mode never hides a block.
    const groups = Array.from(byGroup.values());
    let chosen = groups.find(
      (list) => groupWeeklyCapped(list) || list.some((m) => isAtLimit(m))
    );
    if (!chosen) {
      chosen = groups.find((list) => list.some((m) => isSession5hMetric(m) && (m.percent_used || 0) > 0));
    }
    if (!chosen) chosen = groups.find((list) => list.some((m) => isSession5hMetric(m)));
    if (!chosen) chosen = groups[0] || [];

    const m5h = chosen.find((m) => isSession5hMetric(m));
    const mPrimary = m5h || chosen[0];
    const m7d = chosen.find((m) => isWeeklyMetric(m));
    const weeklyBlocked = groupWeeklyCapped(chosen);
    const primaryBlocked = isAtLimit(mPrimary);
    const isLocked = weeklyBlocked || primaryBlocked;
    const primaryPct =
      mPrimary && typeof mPrimary.percent_used === "number"
        ? Math.round(mPrimary.percent_used)
        : null;
    const weeklyPct =
      m7d && typeof m7d.percent_used === "number" ? Math.round(m7d.percent_used) : null;

    return {
      primaryLabel: mPrimary ? mPrimary.label : "5h",
      primaryPct,
      primaryReset: mPrimary ? formatReset(mPrimary.resets_at, mPrimary.reset_label) : "",
      weeklyPct,
      weeklyBlocked,
      primaryBlocked,
      isLocked,
      weeklyReset: m7d ? formatReset(m7d.resets_at, m7d.reset_label) : "",
    };
  }

  function shortCodeFor(id) {
    const found = COMPACT_ORDER.find(([pid]) => pid === id);
    return found ? found[1] : id.slice(0, 2).toUpperCase();
  }

  function computeMoodAndPeak() {
    let peak = null;
    const weeklyLocked = [];
    const sessionLocked = [];
    for (const [id, snap] of Object.entries(state.snapshots)) {
      if (id === "claude_code" || !snap || snap.status !== "ok") continue;
      let hasWeeklyCap = false;
      let hasOtherCap = false;
      for (const m of snap.metrics || []) {
        if (typeof m.percent_used === "number") {
          peak = peak === null ? m.percent_used : Math.max(peak, m.percent_used);
        }
        if (isAtLimit(m)) {
          if (isWeeklyMetric(m)) hasWeeklyCap = true;
          else hasOtherCap = true;
        }
      }
      if (hasWeeklyCap) weeklyLocked.push(shortCodeFor(id));
      else if (hasOtherCap) sessionLocked.push(shortCodeFor(id));
    }

    if (peak === null) {
      return { peak: null, mood: "sleep", label: "Waiting", sub: "No quota data yet" };
    }
    if (weeklyLocked.length > 0 && sessionLocked.length > 0) {
      return {
        peak,
        mood: "stressed",
        label: "Quota locked",
        sub: `${[...weeklyLocked, ...sessionLocked].join(", ")} at limit`,
      };
    }
    if (weeklyLocked.length > 0) {
      return {
        peak,
        mood: "stressed",
        label: "Weekly locked",
        sub: `${weeklyLocked.join(", ")} locked (7d 100%)`,
      };
    }
    if (sessionLocked.length > 0) {
      return {
        peak,
        mood: "stressed",
        label: "Limit locked",
        sub: `${sessionLocked.join(", ")} locked (100%)`,
      };
    }
    if (peak <= 0.5) {
      return { peak, mood: "sleep", label: "Idle", sub: "0% used" };
    }
    if (peak < 60) {
      return { peak, mood: "happy", label: "All clear", sub: `Peak ${Math.round(peak)}%` };
    }
    if (peak < 85) {
      return { peak, mood: "watch", label: "Getting warm", sub: `Peak ${Math.round(peak)}%` };
    }
    return { peak, mood: "stressed", label: "Near limit", sub: `Peak ${Math.round(peak)}%` };
  }

  function drawCats() {
    window.MaewSprites.renderCatCanvas(els.catCanvas, {
      skin: state.skin,
      mood: state.mood,
      frame: state.frame,
      showHeart: state.showHeart,
    });
    window.MaewSprites.renderCatHead(els.brandCat, state.skin);
  }

  function renderShelf() {
    const info = computeMoodAndPeak();
    state.mood = info.mood;
    els.shelfState.textContent = info.label;
    els.shelfSub.textContent = info.sub;

    els.compactReadout.innerHTML = "";
    let shown = 0;
    for (const [id, tag] of COMPACT_ORDER) {
      const snap = state.snapshots[id];
      if (!snap || snap.status === "disabled") continue;
      if (shown >= 3) break;
      shown += 1;

      const summary = extractCompactSummary(snap);
      const item = document.createElement("span");
      const locked = !!(summary && summary.isLocked);
      const blockedByParent = !!(summary && summary.weeklyBlocked && !summary.primaryBlocked);
      item.className = `compact-item${locked ? " is-locked" : ""}${blockedByParent ? " is-blocked" : ""}`;
      if (summary) {
        const pctTxt = summary.primaryPct !== null ? `${summary.primaryPct}%` : "--";
        if (summary.weeklyBlocked) {
          item.title = `${tag} locked: 7d at 100%${summary.weeklyReset ? ` (resets ${summary.weeklyReset})` : ""} · ${summary.primaryLabel} at ${pctTxt}`;
        } else if (summary.primaryBlocked) {
          item.title = `${tag} locked: ${summary.primaryLabel} at 100%${summary.primaryReset ? ` (resets ${summary.primaryReset})` : ""}${summary.weeklyPct !== null ? ` · 7d: ${summary.weeklyPct}%` : ""}`;
        } else {
          item.title = `${tag} ${summary.primaryLabel}: ${pctTxt}${summary.weeklyPct !== null ? ` · 7d: ${summary.weeklyPct}%` : ""}`;
        }
        item.innerHTML = locked
          ? `<span class="compact-label">${tag}</span>${LOCK_SVG}<span class="compact-val">${pctTxt}</span>`
          : `<span class="compact-label">${tag}</span><span class="compact-val">${pctTxt}</span>`;
      } else {
        item.innerHTML = `<span class="compact-label">${tag}</span><span class="compact-val">--</span>`;
      }
      els.compactReadout.appendChild(item);
    }

    drawCats();
  }

  function statusDotClass(snap) {
    if (!snap) return "warn";
    if (snap.status === "error") return "err";
    if (snap.status === "auth_required" || snap.stale) return "warn";
    const metrics = snap.metrics || [];
    const byGroup = new Map();
    for (const m of metrics) {
      const g = m.group || "";
      if (!byGroup.has(g)) byGroup.set(g, []);
      byGroup.get(g).push(m);
    }
    const groups = Array.from(byGroup.values());
    if (groups.length > 0 && groups.every((list) => list.some((m) => isAtLimit(m)))) {
      return "err";
    }
    if (groups.some((list) => list.some((m) => isAtLimit(m)))) {
      return "warn";
    }
    return "";
  }

  function buildGaugeRow(metric, { blockedByWeekly = false } = {}) {
    const pct = typeof metric.percent_used === "number" ? metric.percent_used : 0;
    const sev = severityKey(metric.percent_used);
    const resetTxt = formatReset(metric.resets_at, metric.reset_label);
    const isFull = isAtLimit(metric);
    const selfLocked = isFull && !blockedByWeekly;

    const row = document.createElement("div");
    row.className = `gauge-row${blockedByWeekly ? " is-blocked" : selfLocked ? " is-locked" : ""}`;

    let rightSub = "";
    if (blockedByWeekly) {
      rightSub = `<span class="blocked-tag" title="Unavailable until weekly (7d) quota resets">${LOCK_SVG}<span>Locked · 7d full</span></span>`;
    } else if (selfLocked) {
      const unlockTxt = resetTxt ? ` · ${escapeHtml(resetTxt)}` : "";
      rightSub = `<span class="blocked-tag" title="Limit reached — locked until reset">${LOCK_SVG}<span>Locked${unlockTxt}</span></span>`;
    } else if (resetTxt) {
      rightSub = `<span class="gauge-reset">${escapeHtml(resetTxt)}</span>`;
    } else if (metric.note) {
      rightSub = `<span class="gauge-reset">${escapeHtml(metric.note)}</span>`;
    }

    row.innerHTML = `
      <div class="gauge-meta">
        <span class="gauge-left">
          <span class="gauge-win">${escapeHtml(metric.label)}</span>
          ${rightSub}
        </span>
        <span class="gauge-pct${selfLocked ? " is-full" : ""}">${Math.round(pct)}%</span>
      </div>
      <div class="bar-track">
        <div class="bar-fill sev-${sev}" style="width:${Math.min(100, Math.max(0, pct))}%"></div>
      </div>
    `;
    return row;
  }

  function buildLocalDrawer(localSnap) {
    const windows = (localSnap.extra && localSnap.extra.windows) || {};
    const w5 = windows["5h"] || { tokens_fmt: "0", cost_fmt: "$0.00" };
    const wt = windows["today"] || { tokens_fmt: "0", cost_fmt: "$0.00" };
    const w7 = windows["7d"] || { tokens_fmt: "0", cost_fmt: "$0.00", by_model: [] };

    const drawer = document.createElement("div");
    drawer.className = "local-drawer";
    drawer.innerHTML = `
      <div class="local-summary-row">
        <div class="local-stat">
          <span class="k">5h local</span>
          <span class="v">${escapeHtml(w5.cost_fmt)}</span>
          <span class="s">${escapeHtml(w5.tokens_fmt)}</span>
        </div>
        <div class="local-stat">
          <span class="k">Today</span>
          <span class="v">${escapeHtml(wt.cost_fmt)}</span>
          <span class="s">${escapeHtml(wt.tokens_fmt)}</span>
        </div>
        <div class="local-stat">
          <span class="k">7d est.</span>
          <span class="v">${escapeHtml(w7.cost_fmt)}</span>
          <span class="s">${escapeHtml(w7.tokens_fmt)}</span>
        </div>
      </div>
    `;

    if (Array.isArray(w7.by_model) && w7.by_model.length) {
      const list = document.createElement("div");
      list.className = "local-models";
      for (const item of w7.by_model.slice(0, 4)) {
        const row = document.createElement("div");
        row.className = "local-model-row";
        row.innerHTML = `
          <span title="${escapeHtml(item.model)}">${escapeHtml(item.model)}</span>
          <span>${escapeHtml(item.tokens_fmt)} · ${escapeHtml(item.cost_fmt)}</span>
        `;
        list.appendChild(row);
      }
      drawer.appendChild(list);
    }
    return drawer;
  }

  function renderClaudeSection() {
    const webSnap = state.snapshots.claude_web;
    const localSnap = state.snapshots.claude_code;
    if (!webSnap && !localSnap) return null;

    const section = document.createElement("section");
    section.className = "provider-section";

    const head = document.createElement("div");
    head.className = "provider-head";

    const title = document.createElement("div");
    title.className = "provider-name";
    title.textContent = "Claude";
    head.appendChild(title);

    const right = document.createElement("div");
    right.className = "provider-right";

    if (localSnap && localSnap.status === "ok") {
      const wToday = localSnap.extra && localSnap.extra.windows && localSnap.extra.windows.today;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `disclosure-btn${state.localDrawerOpen ? " open" : ""}`;
      btn.title = "Toggle offline Claude Code token logs";
      btn.innerHTML = `
        <span>Local${wToday && wToday.tokens_fmt !== "0" ? ` · ${escapeHtml(wToday.tokens_fmt)}` : ""}</span>
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4.5 2.5L8 6l-3.5 3.5"/>
        </svg>
      `;
      btn.onclick = () => {
        state.localDrawerOpen = !state.localDrawerOpen;
        renderProviders();
      };
      right.appendChild(btn);
    }

    const dot = document.createElement("span");
    dot.className = `status-dot ${statusDotClass(webSnap || localSnap)}`.trim();
    right.appendChild(dot);
    head.appendChild(right);
    section.appendChild(head);

    if (webSnap) {
      if (webSnap.status === "auth_required") {
        const notice = document.createElement("div");
        notice.className = "inline-notice";
        notice.innerHTML = `<span>Sign in to view 5h / 7d gauges</span>`;
        const connectBtn = document.createElement("button");
        connectBtn.type = "button";
        connectBtn.className = "btn";
        connectBtn.textContent = "Connect";
        connectBtn.onclick = () => api() && api().open_web_login("claude_web");
        notice.appendChild(connectBtn);
        section.appendChild(notice);
      } else if (webSnap.status === "error" && (!webSnap.metrics || !webSnap.metrics.length)) {
        const notice = document.createElement("div");
        notice.className = "inline-notice";
        notice.textContent = webSnap.error || "Unable to load Claude usage";
        section.appendChild(notice);
      } else {
        const weeklyCapped = groupWeeklyCapped(webSnap.metrics);
        for (const m of webSnap.metrics || []) {
          section.appendChild(
            buildGaugeRow(m, { blockedByWeekly: weeklyCapped && isSession5hMetric(m) })
          );
        }
        if (webSnap.stale && webSnap.error) {
          const note = document.createElement("div");
          note.className = "stale-note";
          note.textContent = `Stale · ${webSnap.error}`;
          section.appendChild(note);
        }
      }
    } else if (localSnap) {
      const notice = document.createElement("div");
      notice.className = "inline-notice";
      notice.textContent = "Web quota disabled · click Local above for offline logs";
      section.appendChild(notice);
    }

    if (localSnap && localSnap.status === "ok" && state.localDrawerOpen) {
      section.appendChild(buildLocalDrawer(localSnap));
    }

    return section;
  }

  function renderGenericSection(snap) {
    const section = document.createElement("section");
    section.className = "provider-section";

    const head = document.createElement("div");
    head.className = "provider-head";
    head.innerHTML = `
      <div class="provider-name">${escapeHtml(snap.display_name)}</div>
      <div class="provider-right">
        <span class="status-dot ${statusDotClass(snap)}"></span>
      </div>
    `;
    section.appendChild(head);

    if (snap.status === "auth_required") {
      const notice = document.createElement("div");
      notice.className = "inline-notice";
      const span = document.createElement("span");
      span.textContent = snap.error || "Setup required";
      notice.appendChild(span);

      const actionBtn = document.createElement("button");
      actionBtn.type = "button";
      actionBtn.className = "btn";
      if (snap.provider === "codex") {
        actionBtn.textContent = "Connect";
        actionBtn.onclick = () => api() && api().open_web_login("codex");
      } else {
        actionBtn.textContent = "Configure";
        actionBtn.onclick = () => switchView("settings");
      }
      notice.appendChild(actionBtn);
      section.appendChild(notice);
      return section;
    }

    if (snap.status === "error" && (!snap.metrics || !snap.metrics.length)) {
      const notice = document.createElement("div");
      notice.className = "inline-notice";
      notice.textContent = snap.error || "Unable to fetch usage";
      section.appendChild(notice);
      return section;
    }

    const groups = new Map();
    for (const m of snap.metrics || []) {
      const key = m.group || "";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(m);
    }

    const showGroupTitles =
      groups.size > 1 ||
      (groups.size === 1 && !groups.has("") && Array.from(groups.keys())[0] !== snap.display_name);

    for (const [groupName, list] of groups.entries()) {
      const block = document.createElement("div");
      block.className = "group-block";
      if (showGroupTitles && groupName) {
        const gTitle = document.createElement("div");
        gTitle.className = "group-title";
        gTitle.textContent = groupName;
        block.appendChild(gTitle);
      }
      const weeklyCapped = groupWeeklyCapped(list);
      for (const m of list) {
        block.appendChild(
          buildGaugeRow(m, { blockedByWeekly: weeklyCapped && isSession5hMetric(m) })
        );
      }
      section.appendChild(block);
    }

    if (snap.stale && snap.error) {
      const note = document.createElement("div");
      note.className = "stale-note";
      note.textContent = `Stale · ${snap.error}`;
      section.appendChild(note);
    }
    return section;
  }

  function renderProviders() {
    els.providersContainer.innerHTML = "";

    const claudeSec = renderClaudeSection();
    if (claudeSec) els.providersContainer.appendChild(claudeSec);

    const displayOrder = ["antigravity", "codex", "copilot", "openrouter", "opencode_go", "minimax"];
    const rendered = new Set(["claude_web", "claude_code"]);
    for (const id of displayOrder) {
      const snap = state.snapshots[id];
      if (!snap || snap.status === "disabled") continue;
      rendered.add(id);
      els.providersContainer.appendChild(renderGenericSection(snap));
    }

    for (const [id, snap] of Object.entries(state.snapshots)) {
      if (rendered.has(id) || !snap || snap.status === "disabled") continue;
      els.providersContainer.appendChild(renderGenericSection(snap));
    }
  }

  function renderProvidersSettings() {
    els.providersSettingsList.innerHTML = "";

    for (const item of PROVIDER_CATALOG) {
      const enabled = !!state.providers[item.id];
      const scan = state.scanResults[item.id];

      const wrap = document.createElement("div");
      wrap.className = "prov-setting-item";

      const top = document.createElement("div");
      top.className = "prov-setting-top";

      const info = document.createElement("div");
      info.className = "prov-setting-info";
      const badge = scan && scan.detected ? `<span class="detect-pill">Detected</span>` : "";
      const subText = scan ? scan.detail : item.subtitle;
      info.innerHTML = `
        <div class="prov-setting-title"><span>${escapeHtml(item.name)}</span>${badge}</div>
        <div class="prov-setting-sub">${escapeHtml(subText)}</div>
      `;

      const sw = document.createElement("button");
      sw.type = "button";
      sw.className = `switch${enabled ? " on" : ""}`;
      sw.setAttribute("role", "switch");
      sw.setAttribute("aria-checked", enabled ? "true" : "false");
      sw.setAttribute("aria-label", `Toggle ${item.name}`);
      sw.onclick = () => {
        state.providers[item.id] = !state.providers[item.id];
        renderProvidersSettings();
      };

      top.appendChild(info);
      top.appendChild(sw);
      wrap.appendChild(top);

      // Show clean inline config ONLY when provider is enabled and has credentials/options
      if (enabled && item.auth === "web") {
        const box = document.createElement("div");
        box.className = "prov-config-box";
        const row = document.createElement("div");
        row.className = "btn-row";
        row.style.marginTop = "0";
        const connBtn = document.createElement("button");
        connBtn.type = "button";
        connBtn.className = "btn";
        connBtn.textContent = `Connect ${item.name}`;
        connBtn.onclick = () => api() && api().open_web_login(item.id);
        const outBtn = document.createElement("button");
        outBtn.type = "button";
        outBtn.className = "btn danger";
        outBtn.textContent = "Sign out";
        outBtn.onclick = () => api() && api().clear_web_session(item.id);
        row.appendChild(connBtn);
        row.appendChild(outBtn);
        box.appendChild(row);
        wrap.appendChild(box);
      } else if (enabled && item.auth === "key") {
        const hasKey = !!state.savedKeys[item.secretKey];
        const box = document.createElement("div");
        box.className = "prov-config-box";

        const keyRow = document.createElement("div");
        keyRow.className = "key-input-row";
        const input = document.createElement("input");
        input.type = "password";
        input.className = "text-input";
        input.placeholder = hasKey ? "Saved (DPAPI encrypted)" : item.placeholder;

        const saveKeyBtn = document.createElement("button");
        saveKeyBtn.type = "button";
        saveKeyBtn.className = "btn";
        saveKeyBtn.textContent = "Set";
        saveKeyBtn.onclick = async () => {
          const val = input.value.trim();
          if (!val || !api()) return;
          const res = await api().set_provider_secret(item.secretKey, val);
          if (res && res.saved_keys) state.savedKeys = res.saved_keys;
          input.value = "";
          renderProvidersSettings();
        };

        keyRow.appendChild(input);
        keyRow.appendChild(saveKeyBtn);

        if (hasKey) {
          const clearBtn = document.createElement("button");
          clearBtn.type = "button";
          clearBtn.className = "btn danger";
          clearBtn.textContent = "Clear";
          clearBtn.onclick = async () => {
            if (!api()) return;
            const res = await api().set_provider_secret(item.secretKey, null);
            if (res && res.saved_keys) state.savedKeys = res.saved_keys;
            renderProvidersSettings();
          };
          keyRow.appendChild(clearBtn);
        }
        box.appendChild(keyRow);

        // Extra clean per-provider option where needed
        if (item.id === "minimax") {
          const meta = document.createElement("div");
          meta.className = "prov-meta-row";
          meta.innerHTML = `<span>Region</span>`;
          const seg = document.createElement("div");
          seg.className = "segmented";
          for (const [regId, regLbl] of [["international", "Intl"], ["china", "China"]]) {
            const b = document.createElement("button");
            b.type = "button";
            b.className = `seg-btn${state.providers.minimax_region === regId ? " active" : ""}`;
            b.textContent = regLbl;
            b.onclick = () => {
              state.providers.minimax_region = regId;
              renderProvidersSettings();
            };
            seg.appendChild(b);
          }
          meta.appendChild(seg);
          box.appendChild(meta);
        } else if (item.id === "copilot") {
          const meta = document.createElement("div");
          meta.className = "prov-meta-row";
          meta.innerHTML = `<span>Monthly quota</span>`;
          const qInput = document.createElement("input");
          qInput.type = "text";
          qInput.inputMode = "numeric";
          qInput.className = "text-input";
          qInput.style.maxWidth = "84px";
          qInput.value = String(state.providers.copilot_monthly_quota || 1500);
          qInput.onchange = () => {
            const n = parseInt(qInput.value, 10);
            if (!Number.isNaN(n) && n > 0) state.providers.copilot_monthly_quota = n;
          };
          meta.appendChild(qInput);
          box.appendChild(meta);
        } else if (item.id === "openrouter") {
          const meta = document.createElement("div");
          meta.className = "prov-meta-row";
          meta.innerHTML = `<span>Daily budget (USD)</span>`;
          const bInput = document.createElement("input");
          bInput.type = "text";
          bInput.inputMode = "decimal";
          bInput.className = "text-input";
          bInput.style.maxWidth = "84px";
          bInput.placeholder = "optional";
          bInput.value = state.providers.openrouter_daily_budget ? String(state.providers.openrouter_daily_budget) : "";
          bInput.onchange = () => {
            const n = parseFloat(bInput.value);
            state.providers.openrouter_daily_budget = !Number.isNaN(n) && n > 0 ? n : null;
          };
          meta.appendChild(bInput);
          box.appendChild(meta);
        }

        wrap.appendChild(box);
      }

      els.providersSettingsList.appendChild(wrap);
    }
  }

  function renderSkinPicker() {
    els.skinGrid.innerHTML = "";
    for (const [skinId, info] of Object.entries(window.MaewSprites.CAT_SKINS)) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `skin-tile${state.skin === skinId ? " active" : ""}`;
      const c = document.createElement("canvas");
      c.className = "pixel";
      c.width = 30;
      c.height = 24;
      window.MaewSprites.renderCatHead(c, skinId);
      const label = document.createElement("span");
      label.textContent = info.name;
      btn.appendChild(c);
      btn.appendChild(label);
      btn.onclick = () => {
        state.skin = skinId;
        drawCats();
        renderSkinPicker();
        if (api()) api().set_cat_skin(skinId);
      };
      els.skinGrid.appendChild(btn);
    }
  }

  function applyTheme(theme) {
    state.theme = theme === "light" ? "light" : "dark";
    document.body.classList.toggle("theme-light", state.theme === "light");
    els.themeDark.classList.toggle("active", state.theme === "dark");
    els.themeLight.classList.toggle("active", state.theme === "light");
  }

  function applyCompact(compact) {
    document.body.classList.toggle("compact", !!compact);
    els.btnCompact.innerHTML = compact
      ? `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 10l4-4 4 4"/></svg>`
      : `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6l4 4 4-4"/></svg>`;
  }

  function syncSettingsUI() {
    els.activeVal.textContent = `${state.activeMin}m`;
    els.idleVal.textContent = `${state.idleMin}m`;
    els.btnPin.classList.toggle("is-active", !!state.alwaysOnTop);
    applyTheme(state.theme);
    renderSkinPicker();
    renderProvidersSettings();
  }

  function stepValue(current, list, delta) {
    let idx = list.findIndex((v) => v >= current);
    if (idx === -1) idx = list.length - 1;
    const nextIdx = Math.max(0, Math.min(list.length - 1, idx + delta));
    return list[nextIdx];
  }

  async function runScan() {
    if (!api()) return;
    els.btnScanProviders.disabled = true;
    try {
      state.scanResults = (await api().scan_providers()) || {};
      renderProvidersSettings();
    } finally {
      els.btnScanProviders.disabled = false;
    }
  }

  function switchView(name) {
    state.view = name;
    els.dashboardView.classList.toggle("hidden", name !== "dashboard");
    els.settingsView.classList.toggle("hidden", name !== "settings");
    els.btnSettings.classList.toggle("is-active", name === "settings");
    if (name === "settings") {
      applyCompact(false);
      if (api()) api().set_compact(false);
      syncSettingsUI();
      if (!Object.keys(state.scanResults).length) runScan();
    }
  }

  window.maewReceiveState = (payload) => {
    if (!payload) return;
    if (payload.saved_keys) state.savedKeys = payload.saved_keys;
    if (payload.config) {
      const cfg = payload.config;
      state.config = cfg;
      state.skin = window.MaewSprites.CAT_SKINS[cfg.window.cat_skin] ? cfg.window.cat_skin : "orange";
      state.theme = cfg.window.theme || "dark";
      state.alwaysOnTop = !!cfg.window.always_on_top;
      state.activeMin = cfg.active_refresh_minutes || 5;
      state.idleMin = cfg.idle_max_refresh_minutes || 60;
      state.providers = { ...state.providers, ...cfg.providers };
      applyTheme(state.theme);
      els.btnPin.classList.toggle("is-active", state.alwaysOnTop);
      if (state.view === "dashboard") {
        applyCompact(cfg.window.compact);
      }
    }
    if (payload.snapshots) state.snapshots = payload.snapshots;
    if (typeof payload.refreshing === "boolean") {
      state.refreshing = payload.refreshing;
      els.btnRefresh.classList.toggle("spinning", state.refreshing);
    }
    if (payload.updated_label) els.footerUpdated.textContent = `Updated ${payload.updated_label}`;
    if (payload.next_refresh_label) els.footerNext.textContent = `Next ${payload.next_refresh_label}`;
    renderShelf();
    renderProviders();
    if (state.view === "settings") renderProvidersSettings();
  };

  els.catPetArea.addEventListener("click", () => {
    state.showHeart = true;
    els.petWhisper.textContent = PET_WHISPERS[Math.floor(Math.random() * PET_WHISPERS.length)];
    els.petWhisper.classList.add("show");
    drawCats();
    clearTimeout(state.heartTimer);
    state.heartTimer = setTimeout(() => {
      state.showHeart = false;
      els.petWhisper.classList.remove("show");
      drawCats();
    }, 1300);
  });

  els.btnCompact.addEventListener("click", () => {
    if (state.view === "settings") switchView("dashboard");
    const next = !document.body.classList.contains("compact");
    applyCompact(next);
    if (api()) api().set_compact(next);
  });

  els.btnRefresh.addEventListener("click", () => api() && api().refresh_now());

  els.btnPin.addEventListener("click", async () => {
    state.alwaysOnTop = !state.alwaysOnTop;
    els.btnPin.classList.toggle("is-active", state.alwaysOnTop);
    if (api()) await api().toggle_always_on_top();
  });

  els.btnSettings.addEventListener("click", () => {
    switchView(state.view === "settings" ? "dashboard" : "settings");
  });

  els.btnBackDash.addEventListener("click", () => switchView("dashboard"));
  els.btnHide.addEventListener("click", () => api() && api().hide_to_tray());
  els.btnScanProviders.addEventListener("click", runScan);

  els.themeDark.addEventListener("click", () => applyTheme("dark"));
  els.themeLight.addEventListener("click", () => applyTheme("light"));

  els.activeDec.addEventListener("click", () => {
    state.activeMin = stepValue(state.activeMin, ACTIVE_STEPS, -1);
    if (state.idleMin < state.activeMin) state.idleMin = state.activeMin;
    syncSettingsUI();
  });
  els.activeInc.addEventListener("click", () => {
    state.activeMin = stepValue(state.activeMin, ACTIVE_STEPS, 1);
    if (state.idleMin < state.activeMin) state.idleMin = state.activeMin;
    syncSettingsUI();
  });
  els.idleDec.addEventListener("click", () => {
    state.idleMin = Math.max(state.activeMin, stepValue(state.idleMin, IDLE_STEPS, -1));
    syncSettingsUI();
  });
  els.idleInc.addEventListener("click", () => {
    state.idleMin = stepValue(state.idleMin, IDLE_STEPS, 1);
    syncSettingsUI();
  });

  els.btnSaveSettings.addEventListener("click", async () => {
    const patch = {
      active_refresh_minutes: state.activeMin,
      idle_max_refresh_minutes: state.idleMin,
      window: {
        cat_skin: state.skin,
        theme: state.theme,
        always_on_top: state.alwaysOnTop,
      },
      providers: { ...state.providers },
    };
    if (api()) await api().save_settings(patch);
    switchView("dashboard");
  });

  setInterval(() => {
    state.frame = (state.frame + 1) % 4;
    drawCats();
  }, 650);

  window.addEventListener("pywebviewready", async () => {
    if (api()) {
      const initial = await api().get_state();
      window.maewReceiveState(initial);
    }
  });

  renderShelf();
})();

(() => {
  const state = {
    settings: null,
    peers: [],
    games: [],
    selectedPeerId: null,
    focusables: [],
    focusIndex: 0,
    view: "pair",
    pollTimer: null,
    padPrev: {},
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.textContent = ""; }, 3500);
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || JSON.stringify(body);
      } catch (_) { /* ignore */ }
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  function showView(name) {
    state.view = name;
    $$(".view").forEach((v) => v.classList.toggle("is-visible", v.id === `view-${name}`));
    $$(".tab").forEach((t) => t.classList.toggle("is-active", t.dataset.view === name));
    rebuildFocus();
  }

  function rebuildFocus() {
    const visible = $(".view.is-visible");
    const tabs = $$(".tab");
    const inView = visible ? $$(".focusable", visible).filter((el) => !el.disabled && el.offsetParent !== null) : [];
    state.focusables = [...tabs, ...inView];
    if (!state.focusables.length) return;
    if (state.focusIndex >= state.focusables.length) state.focusIndex = 0;
    focusAt(state.focusIndex);
  }

  function focusAt(index) {
    if (!state.focusables.length) return;
    state.focusIndex = (index + state.focusables.length) % state.focusables.length;
    const el = state.focusables[state.focusIndex];
    $$(".list-item").forEach((n) => n.classList.remove("is-focused"));
    if (el.classList.contains("list-item")) el.classList.add("is-focused");
    el.focus({ preventScroll: false });
  }

  function moveFocus(delta) {
    focusAt(state.focusIndex + delta);
  }

  function activateFocused() {
    const el = state.focusables[state.focusIndex];
    if (!el) return;
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") return;
    if (el.tagName === "SELECT") {
      el.focus();
      return;
    }
    el.click();
  }

  function goBack() {
    const form = $("#game-form");
    if (form && !form.classList.contains("is-hidden") && state.view === "games") {
      form.classList.add("is-hidden");
      rebuildFocus();
      return;
    }
    showView("pair");
  }

  function cycleTab(dir) {
    const order = ["pair", "games", "transfer", "verify", "help"];
    const i = order.indexOf(state.view);
    const next = order[(i + dir + order.length) % order.length];
    showView(next);
  }

  function renderPeers() {
    const root = $("#peer-list");
    if (!state.peers.length) {
      root.innerHTML = `<div class="list-item meta">No peers yet. Start PC Transfer on the other machine, or add a manual IP.</div>`;
      rebuildFocus();
      return;
    }
    root.innerHTML = state.peers.map((p) => `
      <div class="list-item focusable" tabindex="0" role="listitem" data-action="select-peer" data-id="${p.device_id}">
        <strong>${escapeHtml(p.name)}</strong>
        <div class="meta">${escapeHtml(p.host)}:${p.port} · <span class="badge">${escapeHtml(p.role)}</span></div>
      </div>
    `).join("");
    fillPeerSelect();
    rebuildFocus();
  }

  function fillPeerSelect() {
    const sel = $("#xfer-peer");
    sel.innerHTML = state.peers.map((p) =>
      `<option value="${p.device_id}" ${state.selectedPeerId === p.device_id ? "selected" : ""}>${escapeHtml(p.name)} (${p.host})</option>`
    ).join("") || `<option value="">No peers</option>`;
  }

  function renderGames() {
    const root = $("#game-list");
    if (!state.games.length) {
      root.innerHTML = `<div class="list-item meta">No games registered. Add one or seed the demo.</div>`;
    } else {
      root.innerHTML = state.games.map((g) => `
        <div class="list-item focusable" tabindex="0" role="listitem" data-action="edit-game" data-id="${g.id}">
          <strong>${escapeHtml(g.title)}</strong>
          <div class="meta">Game: ${escapeHtml(g.game_folder)}</div>
          <div class="meta">Saves: ${(g.save_folders || []).map((s) => escapeHtml(s.path)).join(", ") || "—"}</div>
        </div>
      `).join("");
    }
    const xsel = $("#xfer-game");
    xsel.innerHTML = state.games.map((g) =>
      `<option value="${g.id}">${escapeHtml(g.title)}</option>`
    ).join("") || `<option value="">No games</option>`;
    rebuildFocus();
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  async function loadSettings() {
    state.settings = await api("/api/settings");
    $("#device-line").textContent = `${state.settings.device_name} · ${state.settings.role} · :${state.settings.http_port}`;
    $("#set-name").value = state.settings.device_name;
    $("#set-role").value = state.settings.role;
  }

  async function loadPeers() {
    const data = await api("/api/peers");
    state.peers = data.peers || [];
    renderPeers();
  }

  async function loadGames() {
    const data = await api("/api/games");
    state.games = data.games || [];
    renderGames();
  }

  async function pollJob(jobId) {
    const panel = $("#xfer-status");
    clearInterval(state.pollTimer);
    state.pollTimer = setInterval(async () => {
      try {
        const job = await api(`/api/transfer/jobs/${jobId}`);
        panel.textContent = `[${job.stage}] ${job.percent.toFixed(0)}% — ${job.message}`;
        if (job.done) {
          clearInterval(state.pollTimer);
          if (job.error) toast(`Failed: ${job.error}`);
          else toast("Transfer finished");
        }
      } catch (err) {
        clearInterval(state.pollTimer);
        panel.textContent = String(err.message || err);
      }
    }, 500);
  }

  function peerById(id) {
    return state.peers.find((p) => p.device_id === id);
  }

  async function sendTransfer(kind) {
    const gameId = $("#xfer-game").value;
    const peerId = $("#xfer-peer").value;
    const peer = peerById(peerId);
    if (!gameId || !peer) {
      toast("Select a game and peer");
      return;
    }
    const policy = $("#xfer-policy").value;
    const path = kind === "game" ? "/api/transfer/send-game" : "/api/transfer/send-saves";
    $("#xfer-status").textContent = "Starting…";
    try {
      const res = await api(path, {
        method: "POST",
        body: JSON.stringify({
          game_id: gameId,
          peer_host: peer.host,
          peer_port: peer.port,
          policy,
        }),
      });
      toast(`Job ${res.job_id} started`);
      pollJob(res.job_id);
    } catch (err) {
      $("#xfer-status").textContent = String(err.message || err);
      toast(String(err.message || err));
    }
  }

  async function runVerify() {
    const data = await api("/api/games/verify");
    const root = $("#verify-list");
    if (!data.results.length) {
      root.innerHTML = `<div class="list-item meta">Nothing to verify.</div>`;
      rebuildFocus();
      return;
    }
    root.innerHTML = data.results.map((r) => {
      const badge = r.ok ? `<span class="badge ok">OK</span>` : `<span class="badge bad">Issues</span>`;
      const saves = (r.save_folders || []).map((s) =>
        `<div class="meta">Save ${escapeHtml(s.path)} · ${s.exists ? (s.size_label || "") : "MISSING"} · ${s.last_modified || ""}</div>`
      ).join("");
      return `
        <div class="list-item focusable" tabindex="0">
          <strong>${escapeHtml(r.title)} ${badge}</strong>
          <div class="meta">Game ${escapeHtml(r.game_folder.path)} · ${r.game_folder.exists ? r.game_folder.size_label : "MISSING"} · ${r.game_folder.last_modified || ""}</div>
          ${saves}
        </div>`;
    }).join("");
    rebuildFocus();
  }

  function openGameForm(game) {
    const form = $("#game-form");
    form.classList.remove("is-hidden");
    $("#game-form-title").textContent = game ? "Edit game" : "Add game";
    $("#game-id").value = game?.id || "";
    $("#game-title").value = game?.title || "";
    $("#game-folder").value = game?.game_folder || "";
    $("#save-folder").value = game?.save_folders?.[0]?.path || "";
    $("#game-notes").value = game?.notes || "";
    rebuildFocus();
    focusAt(state.focusables.findIndex((el) => el.id === "game-title"));
  }

  // Event delegation
  document.addEventListener("click", async (ev) => {
    const el = ev.target.closest("[data-action]");
    if (!el) return;
    const action = el.dataset.action;
    try {
      if (action === "nav") showView(el.dataset.view);
      else if (action === "refresh-peers") { await loadPeers(); toast("Peers refreshed"); }
      else if (action === "seed-demo") {
        await api("/api/demo/seed", { method: "POST", body: "{}" });
        await loadGames();
        toast("Demo game seeded");
        showView("games");
      }
      else if (action === "new-game") openGameForm(null);
      else if (action === "cancel-game") { $("#game-form").classList.add("is-hidden"); rebuildFocus(); }
      else if (action === "pick") {
        try {
          const res = await api("/api/pick-folder");
          if (res.path) $(`#${el.dataset.target}`).value = res.path;
        } catch (err) {
          toast("Folder picker unavailable — type the path");
        }
      }
      else if (action === "select-peer") {
        state.selectedPeerId = el.dataset.id;
        fillPeerSelect();
        toast("Peer selected");
      }
      else if (action === "edit-game") {
        const game = state.games.find((g) => g.id === el.dataset.id);
        openGameForm(game);
      }
      else if (action === "send-game") await sendTransfer("game");
      else if (action === "send-saves") await sendTransfer("saves");
      else if (action === "run-verify") { await runVerify(); toast("Verification complete"); }
    } catch (err) {
      toast(String(err.message || err));
    }
  });

  $("#manual-peer-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/peers/manual", {
        method: "POST",
        body: JSON.stringify({
          host: $("#manual-host").value.trim(),
          port: Number($("#manual-port").value) || 8787,
          name: $("#manual-name").value.trim() || "Manual peer",
          device_id: `manual-${Date.now()}`,
        }),
      });
      await loadPeers();
      toast("Peer added");
    } catch (err) {
      toast(String(err.message || err));
    }
  });

  $("#settings-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          device_name: $("#set-name").value.trim(),
          role: $("#set-role").value,
        }),
      });
      await loadSettings();
      toast("Settings saved");
    } catch (err) {
      toast(String(err.message || err));
    }
  });

  $("#game-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const savePath = $("#save-folder").value.trim();
    try {
      await api("/api/games", {
        method: "POST",
        body: JSON.stringify({
          id: $("#game-id").value || null,
          title: $("#game-title").value.trim(),
          game_folder: $("#game-folder").value.trim(),
          save_folders: savePath ? [{ label: "Saves", path: savePath }] : [],
          notes: $("#game-notes").value.trim(),
        }),
      });
      $("#game-form").classList.add("is-hidden");
      await loadGames();
      toast("Game saved");
    } catch (err) {
      toast(String(err.message || err));
    }
  });

  // Keyboard
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowRight") {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName) && ev.key === "ArrowRight") return;
      ev.preventDefault();
      moveFocus(1);
    } else if (ev.key === "ArrowUp" || ev.key === "ArrowLeft") {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName) && ev.key === "ArrowLeft") return;
      ev.preventDefault();
      moveFocus(-1);
    } else if (ev.key === "Enter" && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
      ev.preventDefault();
      activateFocused();
    } else if (ev.key === "Escape") {
      goBack();
    }
  });

  // Gamepad
  function buttonPressed(pad, index) {
    const b = pad.buttons[index];
    return typeof b === "object" ? !!b.pressed : b === 1;
  }

  function pollGamepad() {
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    const pad = [...pads].find(Boolean);
    const status = $("#pad-status");
    if (!pad) {
      requestAnimationFrame(pollGamepad);
      return;
    }
    status.textContent = `Connected: ${pad.id}`;

    const pressed = (i) => buttonPressed(pad, i);
    const edge = (i) => {
      const now = pressed(i);
      const was = !!state.padPrev[i];
      state.padPrev[i] = now;
      return now && !was;
    };

    const axX = pad.axes[0] || 0;
    const axY = pad.axes[1] || 0;
    const stickThreshold = 0.55;
    const now = performance.now();
    if (!pollGamepad._nextStick) pollGamepad._nextStick = 0;
    if (now >= pollGamepad._nextStick) {
      if (axY > stickThreshold || pressed(13)) { moveFocus(1); pollGamepad._nextStick = now + 180; }
      else if (axY < -stickThreshold || pressed(12)) { moveFocus(-1); pollGamepad._nextStick = now + 180; }
      else if (axX > stickThreshold || pressed(15)) { moveFocus(1); pollGamepad._nextStick = now + 180; }
      else if (axX < -stickThreshold || pressed(14)) { moveFocus(-1); pollGamepad._nextStick = now + 180; }
    }

    // Standard mapping: 0 A, 1 B, 2 X, 3 Y, 4 LB, 5 RB
    if (edge(0)) activateFocused();
    if (edge(1)) goBack();
    if (edge(2)) showView("transfer");
    if (edge(3)) {
      if (state.view === "pair") loadPeers();
      else if (state.view === "verify") runVerify();
      else showView("verify");
    }
    if (edge(4)) cycleTab(-1);
    if (edge(5)) cycleTab(1);

    requestAnimationFrame(pollGamepad);
  }

  window.addEventListener("gamepadconnected", () => {
    toast("Gamepad connected");
    $("#pad-status").textContent = "Gamepad connected";
  });

  async function boot() {
    await loadSettings();
    await loadPeers();
    await loadGames();
    showView("pair");
    setInterval(() => { loadPeers().catch(() => {}); }, 3000);
    requestAnimationFrame(pollGamepad);
  }

  boot().catch((err) => toast(String(err.message || err)));
})();

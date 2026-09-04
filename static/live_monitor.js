// live_monitor.js -- Live Monitor's page logic, shared between the full
// page (templates/live_monitor.html), its four standalone Dashboard
// widget routes (templates/live_monitor_widget.html, /live/widget/
// selection|cq|noncq|merged), and -- as of the JS-applet migration, see
// /Users/darryl/.claude/plans/crystalline-bouncing-meteor.md -- the same
// four widgets mounted directly as shadow-DOM applets on the /dashboard
// page itself.
//
// mountLiveMonitor(root, ctx, widgetMode) is the one implementation used by
// all of these:
//   - root is either `document` (real page navigation: the full page or a
//     standalone widget route) or a ShadowRoot (mounted as a Dashboard
//     applet) -- both support getElementById/querySelectorAll, so the body
//     below never needs to know which one it has.
//   - ctx is a "feed adapter" -- {on(kind,cb), send(obj), onStatus(cb),
//     listenSpectrum(), unlistenSpectrum()} -- satisfied either by a real
//     owned WebSocket (createOwnWebSocketFeedAdapter() below, for the
//     document-rooted cases) or by the Dashboard's one shared
//     createDashboardLiveFeed() connection (static/dashboard_live.js) --
//     the body below sends/subscribes through this uniformly and never
//     opens a raw WebSocket itself.
//   - widgetMode is 'selection'/'cq'/'noncq' (which CSS-hidden section this
//     particular instance should show) or null/undefined for the full page,
//     which shows all three. The body[data-widget-mode="X"] CSS rule in
//     _live_monitor_body.html handles a document root; :host([data-widget-
//     mode="X"]) handles a shadow root -- mountLiveMonitor sets the
//     attribute on whichever one applies.
//
// -- Resizable columns for every .live-table (cq/noncq/merged all share the
// exact same 9-column shape, so one width set applies to whichever of them
// is actually visible) -- table-layout:fixed (see _live_monitor_body.html)
// means a column's real width comes from its <col style="width:...">, not
// content, so this builds a <colgroup> once per table at mount time and
// wires a drag handle onto each header (except the last column, which has
// nothing to its right to drag against). Widths persist to localStorage --
// shared across every Live Monitor instance/mode in this browser, same
// spirit as the waterfall Rows/Seconds persistence in wsjtx_remote.js.
const LIVE_TABLE_COLUMNS = ['col-time', 'col-band', 'col-mode', 'col-snr', 'col-call', 'col-grid', 'col-dxcc', 'col-message', 'col-flags'];
// Deliberately compact -- these sum to ~550px so the default Dashboard
// tile width (catalog w:6-12) fits without horizontal scroll out of the
// box; DXCC/Message wrap to a second line instead of forcing more width,
// and the resize handles are there for anyone who'd rather have wider
// columns (and the .live-panel-scroll's own overflow-x:auto still covers
// it if a manual resize does end up wider than the tile).
const LIVE_TABLE_DEFAULT_WIDTHS = { 'col-time': 56, 'col-band': 40, 'col-mode': 34, 'col-snr': 42, 'col-call': 72, 'col-grid': 44, 'col-dxcc': 88, 'col-message': 125, 'col-flags': 52 };
const LIVE_TABLE_WIDTHS_KEY = 'live_table_col_widths';
const LIVE_TABLE_MIN_COL_WIDTH = 28;

function loadLiveTableColWidths() {
  const widths = Object.assign({}, LIVE_TABLE_DEFAULT_WIDTHS);
  try {
    Object.assign(widths, JSON.parse(localStorage.getItem(LIVE_TABLE_WIDTHS_KEY) || '{}'));
  } catch (e) { /* ignore corrupt localStorage, fall back to defaults */ }
  return widths;
}

// Sets up every .live-table under `root` for column resizing and returns a
// cleanup() to remove the document-level drag listeners this call adds --
// mountLiveMonitor's own unmount() calls it so a removed Dashboard tile
// doesn't leave a dangling mousemove/mouseup handler behind.
function setupResizableLiveTables(root) {
  const colWidths = loadLiveTableColWidths();
  const tables = root.querySelectorAll('table.live-table');

  function applyWidths() {
    tables.forEach(table => {
      table.querySelectorAll(':scope > colgroup > col').forEach(col => {
        const key = col.dataset.col;
        if (colWidths[key] != null) col.style.width = colWidths[key] + 'px';
      });
    });
  }

  tables.forEach(table => {
    if (table.querySelector(':scope > colgroup')) return; // already set up
    const colgroup = document.createElement('colgroup');
    LIVE_TABLE_COLUMNS.forEach(key => {
      const col = document.createElement('col');
      col.dataset.col = key;
      colgroup.appendChild(col);
    });
    table.insertBefore(colgroup, table.firstChild);

    const ths = table.querySelectorAll('thead th');
    ths.forEach((th, i) => {
      if (i >= LIVE_TABLE_COLUMNS.length - 1) return; // last column: nothing to its right to drag
      const handle = document.createElement('span');
      handle.className = 'col-resize-handle';
      handle.title = 'Drag to resize column';
      handle.addEventListener('mousedown', e => startResize(e, LIVE_TABLE_COLUMNS[i], handle));
      th.appendChild(handle);
    });
  });
  applyWidths();

  let resizing = null;
  function startResize(e, key, handle) {
    e.preventDefault();
    resizing = { key, startX: e.clientX, startWidth: colWidths[key] || LIVE_TABLE_MIN_COL_WIDTH };
    handle.classList.add('active');
  }
  function onMove(e) {
    if (!resizing) return;
    colWidths[resizing.key] = Math.max(LIVE_TABLE_MIN_COL_WIDTH, resizing.startWidth + (e.clientX - resizing.startX));
    applyWidths();
  }
  function onUp() {
    if (!resizing) return;
    resizing = null;
    root.querySelectorAll('.col-resize-handle.active').forEach(h => h.classList.remove('active'));
    try { localStorage.setItem(LIVE_TABLE_WIDTHS_KEY, JSON.stringify(colWidths)); } catch (e) { /* ignore quota errors */ }
  }
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);

  return function cleanup() {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
}

// Returns an unmount() function that clears everything this mount call
// subscribed to on the shared feed -- required for the applet case (a
// removed Dashboard tile's shadow root is discarded, but `ctx` outlives it,
// so leftover subscriptions would otherwise keep firing into detached DOM
// forever). Harmless but unnecessary to call for the document-rooted cases,
// which never get "removed" short of a real page navigation.
function mountLiveMonitor(root, ctx, widgetMode) {
  if (root.host) root.host.setAttribute('data-widget-mode', widgetMode || '');

  const stopResizableTables = setupResizableLiveTables(root);

  const cqBody = root.getElementById('cq-body');
  const nonCqBody = root.getElementById('noncq-body');
  const mergedBody = root.getElementById('merged-body');
  const dot = root.getElementById('conn-dot');
  const connText = root.getElementById('conn-text');
  const statusLine = root.getElementById('live-status');
  const cqFilterBox = root.getElementById('cq-filter');
  const hideWorkedBox = root.getElementById('hide-worked');
  const myCallBox = root.getElementById('my-call');
  const scopeBandBox = root.getElementById('scope-band');
  const scopeModeBox = root.getElementById('scope-mode');
  const MAX_ROWS = 300;
  const timeGroups = { cq: { lastTime: null, alt: false }, noncq: { lastTime: null, alt: false }, merged: { lastTime: null, alt: false } };
  const unsubs = [];

  function fmtTime(ms) {
    if (ms === null || ms === undefined) return '';
    const totalSec = Math.floor(ms / 1000);
    const h = String(Math.floor(totalSec / 3600) % 24).padStart(2, '0');
    const m = String(Math.floor(totalSec / 60) % 60).padStart(2, '0');
    const s = String(totalSec % 60).padStart(2, '0');
    return `${h}:${m}:${s}`;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function timeGroupBold(groupKey, timeMs) {
    const state = timeGroups[groupKey];
    if (state.lastTime !== timeMs) {
      state.lastTime = timeMs;
      state.alt = !state.alt;
    }
    return state.alt;
  }

  function directedAtMe(ev) {
    const mine = (myCallBox.value || '').trim().toUpperCase();
    return !!mine && !!ev.to_call && ev.to_call.toUpperCase() === mine;
  }

  function scopeKey() {
    if (scopeBandBox.checked && scopeModeBox.checked) return 'band_mode';
    if (scopeBandBox.checked) return 'band';
    if (scopeModeBox.checked) return 'mode';
    return 'overall';
  }

  function statusClass(status) {
    return 'status-' + (status || 'unknown');
  }

  function applyStatusColors(tr, ev) {
    const key = scopeKey();
    const callCell = tr.querySelector('.col-call');
    const gridCell = tr.querySelector('.col-grid');
    const dxccCell = tr.querySelector('.col-dxcc');
    if (callCell) callCell.className = 'col-call ' + statusClass(ev.call_status && ev.call_status[key]);
    if (gridCell) gridCell.className = 'col-grid ' + statusClass(ev.grid_status && ev.grid_status[key]);
    if (dxccCell) dxccCell.className = 'col-dxcc ' + statusClass(ev.entity_status && ev.entity_status[key]);
  }

  function sendReply(ev) {
    ctx.send({ action: 'reply', event: ev });
    statusLine.textContent = 'Calling ' + (ev.call || '') + ' in WSJT-X...';
  }

  // -- callsign history popup: MacLoggerDX log summary + full ALL.TXT
  // exchange history for whatever call was clicked --
  const historyOverlay = root.getElementById('history-overlay');
  const historyTitle = root.getElementById('history-title');
  const historySummary = root.getElementById('history-summary');
  const historyLines = root.getElementById('history-lines');

  function openHistory(call) {
    historyTitle.textContent = call;
    historySummary.innerHTML = 'Loading…';
    historyLines.innerHTML = '';
    historyOverlay.style.display = 'flex';
    fetch('/live/callsign/' + encodeURIComponent(call)).then(r => r.json()).then(data => {
      if (data.error) { historySummary.innerHTML = data.error; return; }
      const worked = data.worked_before ? `Worked (${data.qso_count} QSO${data.qso_count === 1 ? '' : 's'})` : 'Never worked';
      const confirmed = data.confirmed_lotw_ever ? 'Confirmed (LoTW)' : (data.confirmed_ever ? 'Confirmed (eQSL/card)' : 'Not confirmed');
      historySummary.innerHTML = `
        <div>${worked}</div>
        <div>${confirmed}</div>
        <div>${data.dxcc_country || 'DXCC unknown'}</div>
        <div>${(data.grids_worked || []).join(', ') || 'No grids on file'}</div>
      `;
      if (!data.exchange_lines.length) {
        historyLines.innerHTML = '<em>No ALL.TXT exchange history found for this call.</em>';
        return;
      }
      // Verbatim ALL.TXT lines, unchanged apart from Tx/Rx coloring.
      historyLines.innerHTML = data.exchange_lines.map(l =>
        `<div class="${l.rxtx === 'Tx' ? 'tx' : ''}">${escapeHtml(l.raw)}</div>`
      ).join('');
    }).catch(e => { historySummary.innerHTML = String(e); });
  }
  root.getElementById('history-close').addEventListener('click', () => { historyOverlay.style.display = 'none'; });

  function buildRow(ev, groupKey) {
    const tr = document.createElement('tr');
    const classes = [];
    if (ev.cq_area_mismatch) classes.push('row-cq-mismatch');
    if (ev.is_new_dxcc) classes.push('row-new-dxcc');
    if (ev.confirmed_ever) classes.push('row-confirmed');
    if (ev.worked_before && !ev.is_new_dxcc) classes.push('row-worked');
    if (directedAtMe(ev)) classes.push('row-directed');
    tr.className = classes.join(' ');
    if (hideWorkedBox.checked && ev.worked_before) tr.style.display = 'none';

    const tags = [];
    if (ev.is_cq) tags.push('<span class="tag tag-cq">CQ' + (ev.cq_directed ? ' ' + ev.cq_directed : '') + '</span>');
    if (ev.is_new_dxcc) tags.push('<span class="tag tag-new">NEW DXCC</span>');
    if (ev.is_new_grid) tags.push('<span class="tag tag-new">NEW GRID</span>');
    if (ev.confirmed_ever) tags.push('<span class="tag tag-confirmed">CFM</span>');
    else if (ev.worked_before) tags.push('<span class="tag tag-worked">WKD</span>');

    const timeClass = timeGroupBold(groupKey, ev.time_ms) ? 'time-bold' : '';
    tr.innerHTML = `
      <td class="col-time ${timeClass}">${fmtTime(ev.time_ms)}</td>
      <td class="col-band">${ev.band || ''}</td>
      <td class="col-mode">${ev.mode || ''}</td>
      <td class="col-snr">${ev.snr ?? ''}</td>
      <td class="col-call"><span class="call-link">${ev.call || ''}</span>${ev.call ? `<a class="qrz-link" href="https://www.qrz.com/db/${encodeURIComponent(ev.call)}" target="_blank" rel="noopener">QRZ</a>` : ''}</td>
      <td class="col-grid">${ev.grid || ''}</td>
      <td class="col-dxcc">${ev.dxcc_name || ''}</td>
      <td class="col-message">${ev.message || ''}</td>
      <td class="col-flags">${tags.join('')}</td>
    `;
    applyStatusColors(tr, ev);
    tr.title = 'Double-click to call ' + (ev.call || 'this station') + ' in WSJT-X';
    tr.addEventListener('dblclick', () => {
      tr.classList.add('row-flash');
      setTimeout(() => tr.classList.remove('row-flash'), 600);
      sendReply(ev);
    });
    const callLink = tr.querySelector('.call-link');
    if (callLink && ev.call) {
      callLink.title = 'Click for callsign history';
      callLink.addEventListener('click', (e) => { e.stopPropagation(); openHistory(ev.call); });
      callLink.addEventListener('dblclick', (e) => { e.stopPropagation(); });
    }
    return tr;
  }

  function insertRow(body, tr) {
    body.prepend(tr);
    while (body.children.length > MAX_ROWS) body.removeChild(body.lastChild);
  }

  function renderDecode(ev) {
    const groupKey = ev.is_cq ? 'cq' : 'noncq';
    insertRow(ev.is_cq ? cqBody : nonCqBody, buildRow(ev, groupKey));
    // Same event, second independently-built row -- see the .live-merged-
    // section note in _live_monitor_body.html for why this always renders
    // regardless of which widget mode is actually showing.
    insertRow(mergedBody, buildRow(ev, 'merged'));
  }

  function recolorAllRows() {
    // Cheap: there's no stored event list, so a scope change just leaves
    // already-rendered rows as-is until new decodes arrive. Re-render from
    // history instead, which we already have server-side. Also doubles as
    // this mount's own catch-up fetch -- see the ctx.on('decode', ...) note
    // near the bottom for why that's needed now.
    fetch('/live/history').then(r => r.json()).then(events => {
      cqBody.innerHTML = '';
      nonCqBody.innerHTML = '';
      mergedBody.innerHTML = '';
      timeGroups.cq.lastTime = timeGroups.noncq.lastTime = timeGroups.merged.lastTime = null;
      timeGroups.cq.alt = timeGroups.noncq.alt = timeGroups.merged.alt = false;
      events.forEach(ev => { if (ev.kind === 'decode') renderDecode(ev); });
    }).catch(() => {});
  }

  function renderStatus(ev) {
    const parts = [];
    if (ev.dial_frequency_hz) parts.push((ev.dial_frequency_hz / 1e6).toFixed(4) + ' MHz');
    if (ev.mode) parts.push(ev.mode);
    if (ev.dx_call) parts.push('DX: ' + ev.dx_call);
    if (ev.transmitting) parts.push('TX');
    statusLine.textContent = parts.length ? parts.join(' | ') : 'Connected to WSJT-X, waiting for status...';
    statusLine.classList.toggle('transmitting', !!ev.transmitting);
  }

  function loadCachedStatus() {
    // Show the last-known status immediately on load/tab-switch instead of
    // waiting for the next live Status broadcast (which can take up to a
    // full T/R period to arrive).
    fetch('/live/config').then(r => r.json()).then(data => {
      if (data.wsjtx_status && Object.keys(data.wsjtx_status).length) renderStatus(data.wsjtx_status);
    }).catch(() => {});
  }

  function pushConfig() {
    fetch('/live/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cq_filter_enabled: cqFilterBox.checked, my_call: myCallBox.value }),
    });
  }
  cqFilterBox.addEventListener('change', pushConfig);
  myCallBox.addEventListener('change', pushConfig);
  scopeBandBox.addEventListener('change', recolorAllRows);
  scopeModeBox.addEventListener('change', recolorAllRows);

  unsubs.push(ctx.onStatus(connected => {
    dot.className = connected ? 'up' : 'down';
    connText.textContent = connected ? 'connected' : 'disconnected -- retrying...';
  }));
  // ctx's feed always connects with no_history=1 (true for both the shared
  // Dashboard connection, which can't replay per-widget on demand, and this
  // file's own standalone adapter below, kept consistent so this mount
  // function never needs to know or care which one it has) -- so an
  // explicit catch-up fetch is always required now, not just in the
  // Dashboard-applet case. recolorAllRows() already does exactly that.
  unsubs.push(ctx.on('decode', renderDecode));
  unsubs.push(ctx.on('status', renderStatus));
  unsubs.push(ctx.on('qso_logged', ev => { statusLine.textContent = 'Logged: ' + (ev.dx_call || ''); }));
  unsubs.push(ctx.on('clear', () => {
    cqBody.innerHTML = ''; nonCqBody.innerHTML = ''; mergedBody.innerHTML = '';
    timeGroups.cq.lastTime = timeGroups.noncq.lastTime = timeGroups.merged.lastTime = null;
    timeGroups.cq.alt = timeGroups.noncq.alt = timeGroups.merged.alt = false;
  }));

  loadCachedStatus();
  recolorAllRows();

  return function unmount() {
    unsubs.forEach(fn => fn());
    stopResizableTables();
  };
}

// -- Standalone feed adapter: same {on, send, onStatus, listenSpectrum,
// unlistenSpectrum} shape as static/dashboard_live.js's
// createDashboardLiveFeed(), but owns its own single-purpose WebSocket --
// used by the two document-rooted cases below (the full page and a
// standalone widget route each still get their own connection, same as
// before this refactor; only the Dashboard-applet case actually shares
// one). Kept in this file rather than factored out since nothing else
// needs it yet -- revisit if a second family's standalone page wants the
// same shape.
function createOwnWebSocketFeedAdapter() {
  let ws = null;
  const listeners = {};
  const statusListeners = [];
  let spectrumRefcount = 0;
  let connected = false;

  function dispatch(ev) {
    const kind = ev && ev.kind;
    if (kind && listeners[kind]) {
      listeners[kind].slice().forEach(cb => { try { cb(ev); } catch (e) { console.error(e); } });
    }
  }

  function setConnected(v) {
    connected = v;
    statusListeners.slice().forEach(cb => { try { cb(connected); } catch (e) { console.error(e); } });
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    ws = new WebSocket(proto + location.host + '/live/ws?no_history=1');
    ws.onopen = () => { setConnected(true); if (spectrumRefcount > 0) send({ action: 'spectrum_listen' }); };
    ws.onclose = () => { setConnected(false); setTimeout(connect, 2000); };
    ws.onerror = () => ws.close();
    ws.onmessage = (msg) => {
      let ev;
      try { ev = JSON.parse(msg.data); } catch (e) { return; }
      dispatch(ev);
    };
  }
  connect();

  return {
    on(kind, cb) {
      (listeners[kind] = listeners[kind] || []).push(cb);
      return () => { listeners[kind] = (listeners[kind] || []).filter(f => f !== cb); };
    },
    onStatus(cb) {
      statusListeners.push(cb);
      cb(connected);
      return () => {
        const i = statusListeners.indexOf(cb);
        if (i >= 0) statusListeners.splice(i, 1);
      };
    },
    send,
    listenSpectrum() { spectrumRefcount++; if (spectrumRefcount === 1) send({ action: 'spectrum_listen' }); },
    unlistenSpectrum() { spectrumRefcount = Math.max(0, spectrumRefcount - 1); if (spectrumRefcount === 0) send({ action: 'spectrum_unlisten' }); },
  };
}

// -- Registration for the Dashboard applet loader (static/dashboard.html's
// mountApplet()) -- harmless to define even when this file is loaded by a
// real page navigation (full page or standalone widget route) below, it
// just adds three entries to a registry nothing looks at outside /dashboard.
window.DashboardApplets = window.DashboardApplets || {};
['selection', 'cq', 'noncq', 'merged'].forEach(mode => {
  window.DashboardApplets['live_' + mode] = {
    mount(root, ctx) { return mountLiveMonitor(root, ctx, mode); },
  };
});

// -- Auto-bootstrap for real page navigations only: the full /live page and
// the three standalone /live/widget/* routes all load this same file via a
// normal <script src> tag and expect it to just run, exactly as before this
// refactor. Guarded on cq-body actually existing in `document` so that
// dashboard.html loading this file purely to populate the registry above
// (its own top-level document has none of these ids) no-ops harmlessly
// instead of throwing on null element lookups.
if (document.getElementById('cq-body')) {
  mountLiveMonitor(document, createOwnWebSocketFeedAdapter(), document.body.dataset.widgetMode || null);
}

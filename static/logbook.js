// logbook.js -- Logbook's page logic, shared between the full page
// (templates/logbook.html), its two standalone Dashboard widget routes
// (templates/logbook_widget.html, /logbook/widget/recent|confirmations),
// and -- as of the JS-applet migration, see
// /Users/darryl/.claude/plans/crystalline-bouncing-meteor.md -- the same
// two widgets mounted directly as shadow-DOM applets on the /dashboard page
// itself.
//
// mountLogbook(root, ctx, widgetMode) is the one implementation used by all
// of these -- see static/live_monitor.js's near-identical header comment
// for the full explanation of root/ctx/widgetMode and why.
//
// One behavior note versus the pre-refactor version: the "Live" checkbox
// used to open/close its own dedicated WebSocket on demand (connected only
// while checked, to avoid an idle connection otherwise). Now that every
// mounted instance -- standalone or shared-Dashboard-feed -- always has a
// live `ctx` connection available from mount time (matching the baseline
// static/live_monitor.js and static/live_entities.js already established),
// the checkbox purely gates *subscription* to ctx's 'qso_logged' event
// instead of the underlying connection's existence. User-facing behavior
// (status text, the 1.5s-debounced refresh-on-log) is unchanged; only the
// resource cost of an unchecked "Live" box on the standalone page changes
// slightly (one already-open shared-shape connection sits idle rather than
// not existing at all) -- accepted as a non-issue at this app's
// single-user LAN scale, same tradeoff already made for the other families.
function mountLogbook(root, ctx, widgetMode) {
  if (root.host) root.host.setAttribute('data-widget-mode', widgetMode || '');

  function postJson(url, body) {
    return fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
    }).then(r => r.json());
  }

  function showResult(el, ok, msg) {
    el.textContent = msg || (ok ? 'OK' : 'Failed');
    el.className = 'action-result ' + (ok ? 'ok' : 'err');
    setTimeout(() => { el.textContent = ''; }, 6000);
  }

  function fmtUtc(epochS) {
    if (!epochS) return '';
    const d = new Date(epochS * 1000);
    return d.toISOString().slice(0, 16).replace('T', ' ');
  }

  function fmtConfirmedDate(yyyymmdd) {
    if (!yyyymmdd || yyyymmdd.length !== 8) return yyyymmdd || '';
    return `${yyyymmdd.slice(0, 4)}-${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)}`;
  }

  function badge(label) {
    return label ? `<span class="badge badge-${label}">${label}</span>` : '';
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function callCell(call) {
    if (!call) return '';
    return `<span class="call-link" title="Click for callsign history">${escapeHtml(call)}</span>`;
  }

  // -- Recent QSOs --
  const hoursInput = root.getElementById('lb-hours');
  const recentBody = root.getElementById('lb-recent-body');
  const recentResult = root.getElementById('lb-recent-result');
  const yearSelect = root.getElementById('lb-year');
  const monthRow = root.getElementById('lb-month-row');

  function newTags(r) {
    const tags = [];
    if (r.is_new_dxcc) tags.push('<span class="tag tag-new">NEW DXCC</span>');
    else if (r.is_new_band) tags.push('<span class="tag tag-new">NEW BAND</span>');
    return tags.join('');
  }

  function renderRecentRows(rows) {
    if (!rows.length) {
      recentBody.innerHTML = '<tr><td colspan="9" class="lb-empty">No QSOs in this window.</td></tr>';
      return;
    }
    recentBody.innerHTML = rows.map(r => `
      <tr>
        <td>${fmtUtc(r.qso_start)}</td>
        <td>${r.band_tx || r.band_rx || ''}</td>
        <td>${r.mode || ''}</td>
        <td>${callCell(r.call)}</td>
        <td>${r.dxcc_country || ''}${newTags(r)}</td>
        <td>${r.grid || ''}</td>
        <td>${r.rst_sent || ''}</td>
        <td>${r.rst_received || ''}</td>
        <td>${badge(r.qsl_badge)}</td>
      </tr>
    `).join('');
    recentBody.querySelectorAll('.call-link').forEach(el => {
      el.addEventListener('click', () => openHistory(el.textContent));
    });
  }

  // -- Callsign search: reuses the same /live/callsign/<call> history
  // lookup and modal already used by Live Monitor/Remote (worked/confirmed
  // summary + every ALL.TXT exchange line for that call), rather than
  // building a second history view from scratch.
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
      historyLines.innerHTML = data.exchange_lines.map(l =>
        `<div class="${l.rxtx === 'Tx' ? 'tx' : ''}">${escapeHtml(l.raw)}</div>`
      ).join('');
    }).catch(e => { historySummary.innerHTML = String(e); });
  }
  root.getElementById('history-close').addEventListener('click', () => { historyOverlay.style.display = 'none'; });

  const searchInput = root.getElementById('lb-search-call');
  const searchBtn = root.getElementById('lb-search-btn');
  function doSearch() {
    const call = searchInput.value.trim();
    if (call) openHistory(call);
  }
  searchBtn.addEventListener('click', doSearch);
  searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });

  function clearMonthSelection() {
    monthRow.querySelectorAll('button').forEach(b => b.classList.remove('current'));
  }

  function loadRecent() {
    clearMonthSelection();
    const hours = parseFloat(hoursInput.value) || 36;
    fetch(`/logbook/recent?hours=${hours}`).then(r => r.json()).then(rows => {
      if (rows.error) { showResult(recentResult, false, rows.error); return; }
      renderRecentRows(rows);
    }).catch(e => showResult(recentResult, false, String(e)));
  }
  root.getElementById('lb-recent-refresh').addEventListener('click', loadRecent);

  // -- Year/month history browsing: pick a year from the dropdown, then a
  // month button to load that whole calendar month. Selecting a month
  // implies you're not watching "recent" anymore, so it turns Live off --
  // otherwise a live qso_logged event would silently refetch the rolling
  // "last N hours" window over whatever month you were looking at.
  const thisYear = new Date().getUTCFullYear();
  for (let y = thisYear; y >= 1990; y--) {
    const opt = document.createElement('option');
    opt.value = y; opt.textContent = y;
    yearSelect.appendChild(opt);
  }

  function loadMonth(monthBtn) {
    // Turn Live off without going through its full "change" handling --
    // that would call loadRecent() as part of returning to the recent
    // view, racing with (and getting overwritten by, but wastefully) the
    // month fetch below. disconnectLive() is just the subscription teardown.
    if (liveBox.checked) { liveBox.checked = false; disconnectLive(); }
    clearMonthSelection();
    monthBtn.classList.add('current');
    const year = parseInt(yearSelect.value, 10);
    const month = parseInt(monthBtn.dataset.month, 10);
    fetch(`/logbook/month?year=${year}&month=${month}`).then(r => r.json()).then(rows => {
      if (rows.error) { showResult(recentResult, false, rows.error); return; }
      renderRecentRows(rows);
    }).catch(e => showResult(recentResult, false, String(e)));
  }

  monthRow.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => loadMonth(btn));
  });

  yearSelect.addEventListener('change', () => {
    const current = monthRow.querySelector('button.current');
    if (current) loadMonth(current);
  });

  // -- Live toggle: subscribe to the same live feed every other family
  // uses and just refetch Recent QSOs when WSJT-X reports a QSO was logged
  // -- that event only carries a callsign (live_monitor.py's qso_logged
  // broadcast), not full QSO fields, so there's nothing to incrementally
  // splice in; a plain refetch is both simpler and correct. Small delay
  // since MacLoggerDX ingests the same UDP broadcast independently and
  // needs a moment to write its own row.
  //
  // Both directions of the toggle need to actively resync the table, not
  // just start/stop listening -- otherwise "going back into non-live mode"
  // (or back into it) leaves whatever was last on screen (e.g. a browsed
  // history month, or a stale live snapshot) sitting there looking current
  // when it isn't. loadRecent() already clears any month selection, so
  // reusing it here also cleanly exits history-browsing on either edge.
  const liveBox = root.getElementById('lb-live');
  const liveStatus = root.getElementById('lb-live-status');
  let liveRefreshTimer = null;
  let liveStatusUnsub = null;
  let qsoLoggedUnsub = null;

  function disconnectLive() {
    if (liveRefreshTimer !== null) { clearTimeout(liveRefreshTimer); liveRefreshTimer = null; }
    if (liveStatusUnsub) { liveStatusUnsub(); liveStatusUnsub = null; }
    if (qsoLoggedUnsub) { qsoLoggedUnsub(); qsoLoggedUnsub = null; }
    liveStatus.textContent = '';
  }

  function connectLive() {
    liveStatusUnsub = ctx.onStatus(connected => {
      liveStatus.textContent = connected ? 'connected' : 'disconnected -- retrying...';
    });
    qsoLoggedUnsub = ctx.on('qso_logged', () => {
      if (liveRefreshTimer !== null) clearTimeout(liveRefreshTimer);
      liveRefreshTimer = setTimeout(() => { liveRefreshTimer = null; loadRecent(); }, 1500);
    });
  }

  liveBox.addEventListener('change', () => {
    if (liveBox.checked) {
      liveStatus.textContent = 'connecting…';
      loadRecent(); // resync to the current recent view, exiting any history month
      connectLive();
    } else {
      disconnectLive();
      loadRecent(); // land on a real non-live snapshot, not a frozen last-live-update
    }
  });

  // -- Confirmations --
  const monthsInput = root.getElementById('lb-months');
  const confirmBody = root.getElementById('lb-confirm-body');
  const confirmResult = root.getElementById('lb-confirm-result');

  function loadConfirmations() {
    const months = parseFloat(monthsInput.value) || 3;
    fetch(`/logbook/confirmations?months=${months}`).then(r => r.json()).then(rows => {
      if (rows.error) { showResult(confirmResult, false, rows.error); return; }
      if (!rows.length) {
        confirmBody.innerHTML = '<tr><td colspan="7" class="lb-empty">No confirmations in this window.</td></tr>';
        return;
      }
      confirmBody.innerHTML = rows.map(r => `
        <tr>
          <td>${fmtConfirmedDate(r.confirmed_date)}</td>
          <td>${badge(r.confirmed_via)}</td>
          <td>${r.call || ''}</td>
          <td>${r.dxcc_country || ''}${newTags(r)}</td>
          <td>${r.band_tx || ''}</td>
          <td>${r.mode || ''}</td>
          <td>${fmtUtc(r.qso_start)}</td>
        </tr>
      `).join('');
    }).catch(e => showResult(confirmResult, false, String(e)));
  }
  root.getElementById('lb-confirm-refresh').addEventListener('click', loadConfirmations);

  const checkResult = root.getElementById('lb-check-result');
  // MacLoggerDX's own lotwConfirmations AppleScript command returns near-
  // instantly but the real LoTW download keeps running inside MacLoggerDX
  // itself afterward -- there's no signal from outside to know when it's
  // actually done (see trigger_lotw_check()'s docstring in logbook.py), so
  // this just waits a fixed 10s and then refreshes the confirmations table,
  // same as manually clicking Refresh afterward.
  root.getElementById('lb-check-lotw').addEventListener('click', () => {
    postJson('/logbook/check_lotw', {}).then(d => {
      showResult(checkResult, d.ok, d.ok ? `${d.message} -- refreshing confirmations in 10s...` : d.message);
      if (d.ok) setTimeout(loadConfirmations, 10000);
    }).catch(e => showResult(checkResult, false, String(e)));
  });
  root.getElementById('lb-check-eqsl').addEventListener('click', () => {
    postJson('/logbook/check_eqsl', {}).then(d => showResult(checkResult, d.ok, d.message))
      .catch(e => showResult(checkResult, false, String(e)));
  });

  loadRecent();
  loadConfirmations();

  return function unmount() {
    disconnectLive();
  };
}

// -- Registration for the Dashboard applet loader (static/dashboard.html's
// mountApplet()) -- harmless to define even when this file is loaded by a
// real page navigation (full page or standalone widget route) below, it
// just adds two entries to a registry nothing looks at outside /dashboard.
window.DashboardApplets = window.DashboardApplets || {};
['recent', 'confirmations'].forEach(mode => {
  window.DashboardApplets['logbook_' + (mode === 'confirmations' ? 'confirm' : mode)] = {
    mount(root, ctx) { return mountLogbook(root, ctx, mode); },
  };
});

// -- Standalone feed adapter: same {on, send, onStatus, listenSpectrum,
// unlistenSpectrum} shape as static/dashboard_live.js's
// createDashboardLiveFeed() and the other families' copies -- this file
// only ever uses `on('qso_logged', ...)` and `onStatus(...)`, but keeps the
// full shape so mountLogbook never needs to know or care which context
// it's running in. Duplicated rather than shared -- see
// static/live_entities.js's identical note for why.
function createOwnWebSocketFeedAdapterForLogbook() {
  let ws = null;
  const listeners = {};
  const statusListeners = [];
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
    ws = new WebSocket(proto + location.host + '/live/ws');
    ws.onopen = () => setConnected(true);
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
    listenSpectrum() {},
    unlistenSpectrum() {},
  };
}

// -- Auto-bootstrap for real page navigations only: the full /logbook page
// and the two standalone /logbook/widget/* routes all load this same file
// via a normal <script src> tag and expect it to just run, exactly as
// before this refactor. Guarded on lb-recent-body actually existing in
// `document` so that dashboard.html loading this file purely to populate
// the registry above (its own top-level document has none of these ids)
// no-ops harmlessly instead of throwing on null element lookups.
if (document.getElementById('lb-recent-body')) {
  mountLogbook(document, createOwnWebSocketFeedAdapterForLogbook(), document.body.dataset.widgetMode || null);
}

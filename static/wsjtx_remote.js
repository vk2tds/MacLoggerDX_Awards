// wsjtx_remote.js -- WSJT-X Remote's page logic, shared between the full
// page (templates/wsjtx_remote.html), its four standalone Dashboard widget
// routes (templates/wsjtx_remote_widget.html, /remote/widget/band_activity,
// /remote/widget/rx_freq, /remote/widget/waterfall, /remote/widget/rest),
// and -- as of the JS-applet migration, see
// /Users/darryl/.claude/plans/crystalline-bouncing-meteor.md -- the same
// four widgets mounted directly as shadow-DOM applets on the /dashboard
// page itself.
//
// mountWsjtxRemote(root, ctx, widgetMode) is the one implementation used by
// all of these -- same root/ctx/widgetMode contract as
// static/live_monitor.js's mountLiveMonitor() (see its header comment for
// the full explanation), including the "always populate every section
// regardless of which one is actually visible" approach: renderDecode()
// always writes into both the Band Activity and Rx Frequency tables even in
// a widget where one of them is CSS-hidden.
function mountWsjtxRemote(root, ctx, widgetMode) {
  if (root.host) root.host.setAttribute('data-widget-mode', widgetMode || '');

  const dot = root.getElementById('rconn-dot');
  const connText = root.getElementById('rconn-text');
  const statusFreq = root.getElementById('status-freq');
  const statusMode = root.getElementById('status-mode');
  const statusStrip = root.getElementById('status-strip');
  const statusTxLabel = root.getElementById('status-tx-label');
  const statusDx = root.getElementById('status-dx');
  const statusDxGrid = root.getElementById('status-dxgrid');
  const statusLastTx = root.getElementById('status-lasttx');
  const bandBody = root.getElementById('band-activity-body');
  const rxFreqBody = root.getElementById('rx-freq-body');
  const rxFreqWindow = root.getElementById('rxfreq-window');
  const modeStack = root.getElementById('mode-stack');
  const bandRow = root.querySelector('.band-row');
  const myCallBox = root.getElementById('my-call');
  const guiStopBtn = root.getElementById('gui-stop-btn');
  const guiMonitor = root.getElementById('gui-monitor');
  const guiDecode = root.getElementById('gui-decode');
  const guiEnableTx = root.getElementById('gui-enable-tx');
  const guiTune = root.getElementById('gui-tune');
  const guiBridgeHint = root.getElementById('gui-bridge-hint');
  const MAX_ROWS = 200;
  let currentRxDf = null;
  let currentDialHz = null;
  const timeGroups = { band: { lastTime: null, alt: false }, rxfreq: { lastTime: null, alt: false } };
  const unsubs = [];

  // -- Decode-based waterfall (createWaterfall() in static/waterfall.js,
  // shared with the standalone /remote/waterfall tab): WSJT-X's UDP API
  // carries no spectrum/noise data, so this buckets decode events by their
  // (already cycle-quantized) time_ms into rows and plots each decode as an
  // SNR-colored blob at its audio frequency. --
  const wfRowsInput = root.getElementById('wf-rows');
  const wfRowsLabel = root.getElementById('wf-rows-label');
  const wfShowBox = root.getElementById('wf-show');
  const waterfallBlock = root.getElementById('waterfall-block');
  const savedRows = parseInt(localStorage.getItem('wf_rows'), 10);
  // In a Dashboard widget/applet context (any real widgetMode), the tile is
  // an actually-resizable GridStack box -- autoFit keeps the canvas synced
  // to it via ResizeObserver (see static/waterfall.js's comment) instead of
  // the fixed-size-plus-manual-input behavior the full page keeps. The
  // manual Rows input still shows the live row count (onRowsChanged keeps
  // it in sync) but is disabled since the tile's own size is now what
  // controls it.
  const isWidget = !!widgetMode;
  const wf = createWaterfall(root.getElementById('waterfall-canvas'), {
    rows: savedRows || 4,
    autoFit: isWidget,
    onRowsChanged: isWidget ? (n => { wfRowsInput.value = n; }) : null,
  });
  wfRowsInput.value = wf.rows;
  wfRowsInput.disabled = isWidget;

  wfRowsInput.addEventListener('change', () => {
    const n = wf.resize(parseInt(wfRowsInput.value, 10));
    wfRowsInput.value = n;
    localStorage.setItem('wf_rows', String(n));
  });

  // Tells the shared feed whether this mount currently wants spectrum data
  // -- audio_spectrum.py only opens the audio stream while at least one
  // client somewhere is actually listening (see its module docstring), and
  // ctx.listenSpectrum()/unlistenSpectrum() are refcounted so more than one
  // mounted widget wanting it at once doesn't turn it off early. Tracks its
  // own subscribed flag so repeated calls with the same desired state don't
  // double-count the refcount. Defined up here (before wfMode exists) but
  // only ever called later -- function declarations are hoisted, so this is
  // safe.
  let spectrumSubscribed = false;
  function updateSpectrumSubscription() {
    const wantSpectrum = wfShowBox.checked && (wfMode === 'spectrum_4hz' || wfMode === 'spectrum_1hz');
    if (wantSpectrum === spectrumSubscribed) return;
    spectrumSubscribed = wantSpectrum;
    if (wantSpectrum) ctx.listenSpectrum(); else ctx.unlistenSpectrum();
  }

  const savedShow = localStorage.getItem('wf_show');
  if (savedShow !== null) wfShowBox.checked = savedShow === '1';
  waterfallBlock.style.display = wfShowBox.checked ? '' : 'none';
  wfShowBox.addEventListener('change', () => {
    waterfallBlock.style.display = wfShowBox.checked ? '' : 'none';
    localStorage.setItem('wf_show', wfShowBox.checked ? '1' : '0');
    updateSpectrumSubscription();
  });

  // -- Spectrum waterfall mode selector (audio_spectrum.py, real FFT of
  // WSJT-X's own audio input) -- alternative to the decode-based waterfall
  // above, selected client-side since both spectrum_4hz/spectrum_1hz are
  // always being broadcast. Separate localStorage key from the standalone
  // /remote/waterfall tab (wf_mode_standalone) since this panel's mode can
  // legitimately differ.
  const decodeShell = root.getElementById('decode-shell');
  const spectrumShell = root.getElementById('spectrum-shell');
  const spectrumWarn = root.getElementById('spectrum-warn');
  const modeRadios = root.querySelectorAll('input[name="wf-mode"]');
  const specSecondsInput = root.getElementById('spec-seconds');
  const specSecondsLabel = root.getElementById('spec-seconds-label');
  const spectrum = createSpectrumWaterfall(root.getElementById('spectrum-canvas'), {
    autoFit: isWidget,
    onSecondsChanged: isWidget ? (s => { specSecondsInput.value = s; }) : null,
  });
  const savedSeconds = parseInt(localStorage.getItem('spec_seconds_embedded'), 10);
  specSecondsInput.value = spectrum.setSeconds(savedSeconds || 20);
  specSecondsInput.disabled = isWidget;
  specSecondsInput.addEventListener('change', () => {
    const n = spectrum.setSeconds(parseInt(specSecondsInput.value, 10));
    specSecondsInput.value = n;
    localStorage.setItem('spec_seconds_embedded', String(n));
  });

  let wfMode = localStorage.getItem('wf_mode_embedded') || 'decode';
  function applyWfMode() {
    modeRadios.forEach(r => { r.checked = (r.value === wfMode); });
    const isSpectrum = wfMode !== 'decode';
    decodeShell.style.display = isSpectrum ? 'none' : '';
    spectrumShell.style.display = isSpectrum ? '' : 'none';
    wfRowsLabel.style.display = isSpectrum ? 'none' : '';
    specSecondsLabel.style.display = isSpectrum ? '' : 'none';
    if (isSpectrum) spectrum.setRate(wfMode === 'spectrum_4hz' ? 4 : 1);
    updateSpectrumSubscription();
  }
  modeRadios.forEach(r => r.addEventListener('change', () => {
    if (r.checked) { wfMode = r.value; localStorage.setItem('wf_mode_embedded', wfMode); applyWfMode(); }
  }));
  applyWfMode();

  fetch('/live/spectrum_status').then(r => r.json()).then(s => {
    // "capturing: false" is the expected lazy state whenever nobody's
    // listening yet -- only a real "error" means something's actually wrong.
    if (s.error) {
      spectrumWarn.textContent = 'Spectrum capture unavailable: ' + s.error;
      spectrumWarn.style.display = '';
    }
  }).catch(() => {});

  // -- Band-select buttons, driven by Frequencies-tab presets flagged
  // "Remote" -- tunes the rig directly via rigctld (/radio/frequency)
  // instead of clicking WSJT-X's own band button, per the user's own
  // "move away from WSJT-X band buttons" direction. Fetched once on load;
  // edit the Frequencies tab and reload this page to pick up changes.
  let remoteBandPresets = [];

  function loadRemoteBandPresets() {
    fetch('/frequencies/presets').then(r => r.json()).then(d => {
      remoteBandPresets = (d.presets || []).filter(p => p.remote);
      bandRow.innerHTML = '';
      if (remoteBandPresets.length === 0) {
        bandRow.textContent = 'No presets flagged "Remote" -- add some on the Frequencies tab.';
        return;
      }
      remoteBandPresets.forEach(p => {
        const btn = document.createElement('button');
        btn.className = 'band-btn';
        btn.textContent = p.name;
        btn.title = `${(p.freq_hz / 1e6).toFixed(6)} MHz`;
        btn.dataset.freqHz = p.freq_hz;
        btn.addEventListener('click', () => tuneToFreq(p.freq_hz));
        bandRow.appendChild(btn);
      });
      updateBandHighlight();
    }).catch(() => {});
  }

  function tuneToFreq(freqHz) {
    postJson('/radio/frequency', { frequency_hz: freqHz }).then(d => {
      if (!d.ok) { guiBridgeHint.textContent = d.error; guiBridgeHint.className = 'proc-hint err'; }
    }).catch(e => { guiBridgeHint.textContent = String(e); guiBridgeHint.className = 'proc-hint err'; });
  }

  function fmtTime(ms) {
    if (ms === null || ms === undefined) return '';
    const totalSec = Math.floor(ms / 1000);
    const h = String(Math.floor(totalSec / 3600) % 24).padStart(2, '0');
    const m = String(Math.floor(totalSec / 60) % 60).padStart(2, '0');
    const s = String(totalSec % 60).padStart(2, '0');
    return `${h}:${m}:${s}`;
  }

  function statusClass(status) {
    return 'status-' + (status || 'unknown');
  }

  function fmtDt(dt) {
    return (dt === null || dt === undefined) ? '' : dt.toFixed(1);
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function fmtUtc(epochS) {
    if (!epochS) return '';
    const d = new Date(epochS * 1000);
    const p = n => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
           `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
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

  function sendReply(ev) {
    ctx.send({ action: 'reply', event: ev });
    statusLastTx.textContent = 'Calling ' + (ev.call || '') + '...';
  }

  // -- callsign history popup: MacLoggerDX log summary + full ALL.TXT
  // exchange history for whatever call was clicked (shares /live/callsign
  // with Live Monitor rather than re-indexing anything here) --
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

  function makeRow(ev, groupKey) {
    const tr = document.createElement('tr');
    const classes = [];
    if (ev.is_cq) classes.push('row-cq');
    if (directedAtMe(ev)) classes.push('row-directed');
    tr.className = classes.join(' ');
    const dt = ev.delta_time_s ?? ev.raw?.delta_time_s;
    const timeClass = timeGroupBold(groupKey, ev.time_ms) ? 'time-bold' : '';
    tr.innerHTML = `
      <td class="${timeClass}">${fmtTime(ev.time_ms)}</td>
      <td class="col-snr">${ev.snr ?? ''}</td>
      <td>${fmtDt(dt)}</td>
      <td>${ev.delta_freq_hz ?? ''}</td>
      <td class="${statusClass(ev.call_status && ev.call_status.band)}"><span class="call-link">${ev.call || ''}</span>${ev.call ? `<a class="qrz-link" href="https://www.qrz.com/db/${encodeURIComponent(ev.call)}" target="_blank" rel="noopener">QRZ</a>` : ''}</td>
      <td class="${statusClass(ev.entity_status && ev.entity_status.band)}">${ev.dxcc_name || ''}</td>
      <td>${ev.message || ''}</td>
    `;
    tr.title = 'Double-click to call ' + (ev.call || 'this station');
    tr.addEventListener('dblclick', () => sendReply(ev));
    const callLink = tr.querySelector('.call-link');
    if (callLink && ev.call) {
      callLink.title = 'Click for callsign history';
      callLink.addEventListener('click', (e) => { e.stopPropagation(); openHistory(ev.call); });
      callLink.addEventListener('dblclick', (e) => { e.stopPropagation(); });
    }
    return tr;
  }

  function renderDecode(ev) {
    bandBody.prepend(makeRow(ev, 'band'));
    while (bandBody.children.length > MAX_ROWS) bandBody.removeChild(bandBody.lastChild);
    wf.onDecode(ev);

    const windowHz = parseInt(rxFreqWindow.value, 10) || 100;
    if (currentRxDf !== null && ev.delta_freq_hz !== null && ev.delta_freq_hz !== undefined &&
        Math.abs(ev.delta_freq_hz - currentRxDf) <= windowHz) {
      rxFreqBody.prepend(makeRow(ev, 'rxfreq'));
      while (rxFreqBody.children.length > MAX_ROWS) rxFreqBody.removeChild(rxFreqBody.lastChild);
    }
  }

  function updateBandHighlight() {
    if (currentDialHz === null) return;
    // Exact frequency match, not a band-wide one -- presets on the same
    // band but different exact frequencies (e.g. B20M vs B20MC2) should
    // only highlight the one actually in use.
    bandRow.querySelectorAll('.band-btn').forEach(btn => {
      btn.classList.toggle('current', Number(btn.dataset.freqHz) === currentDialHz);
    });
  }

  function renderStatus(ev) {
    if (ev.dial_frequency_hz) {
      currentDialHz = ev.dial_frequency_hz;
      statusFreq.textContent = (ev.dial_frequency_hz / 1e6).toFixed(6);
      updateBandHighlight();
    }
    if (ev.mode) {
      statusMode.textContent = ev.mode;
      modeStack.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.mode === ev.mode));
    }
    if (ev.dx_call) statusDx.textContent = ev.dx_call;
    statusDxGrid.textContent = ev.dx_grid || '';
    if (ev.transmitting) {
      statusTxLabel.textContent = 'Transmitting';
      statusStrip.className = 'status-strip tx';
    } else {
      statusTxLabel.textContent = 'Receiving';
      statusStrip.className = 'status-strip rx';
    }
    if (ev.rx_df !== undefined && ev.rx_df !== null) currentRxDf = ev.rx_df;
    if (ev.tx_message) statusLastTx.textContent = ev.tx_message;
  }

  function loadCachedStatus() {
    // Show the last-known status immediately on load/tab-switch instead of
    // waiting for the next live Status broadcast (which can take up to a
    // full T/R period to arrive).
    fetch('/live/config').then(r => r.json()).then(data => {
      if (data.wsjtx_status && Object.keys(data.wsjtx_status).length) renderStatus(data.wsjtx_status);
    }).catch(() => {});
  }

  loadCachedStatus();
  unsubs.push(ctx.onStatus(connected => {
    dot.className = connected ? 'dot up' : 'dot down';
    connText.textContent = connected ? 'connected' : 'disconnected -- retrying...';
    // No manual re-subscribe needed on reconnect -- ctx's underlying feed
    // (shared or standalone, see createOwnWebSocketFeedAdapter() below)
    // already re-sends spectrum_listen itself if the refcount is still > 0.
  }));
  unsubs.push(ctx.on('decode', renderDecode));
  unsubs.push(ctx.on('status', renderStatus));
  unsubs.push(ctx.on('clear', () => {
    bandBody.innerHTML = ''; rxFreqBody.innerHTML = '';
    timeGroups.band.lastTime = timeGroups.rxfreq.lastTime = null;
    timeGroups.band.alt = timeGroups.rxfreq.alt = false;
    wf.clear();
  }));
  unsubs.push(ctx.on('spectrum_4hz', ev => { if (wfMode === 'spectrum_4hz') spectrum.pushRow(ev.bins); }));
  unsubs.push(ctx.on('spectrum_1hz', ev => { if (wfMode === 'spectrum_1hz') spectrum.pushRow(ev.bins); }));

  function showResult(el, ok, msg) {
    el.textContent = msg || (ok ? 'OK' : 'Failed');
    el.className = 'action-result ' + (ok ? 'ok' : 'err');
    setTimeout(() => { el.textContent = ''; }, 4000);
  }

  function postJson(url, body) {
    return fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
    }).then(r => r.json());
  }

  // -- GUI-scripting bridge (wsjtx_gui_bridge.py): drives WSJT-X's own
  // window directly for the few controls with no UDP equivalent -- Stop,
  // Monitor, Decode, Enable Tx, Tune, and the mode buttons (band buttons
  // moved to direct rigctld control -- see loadRemoteBandPresets() above).
  // Enable Tx/
  // Tune arm via a genuine HID-level click (see wsjtx_gui_bridge.py's
  // module docstring, 2026-07-16) and can take a few seconds with retries;
  // turning them off goes through the ordinary Halt Tx UDP path instead of
  // another GUI click, since that's already proven reliable. Requires
  // WSJT-X running, this app to have Accessibility permission (System
  // Settings -> Privacy & Security -> Accessibility), and
  // pyobjc-framework-Quartz installed; errors from that surface in
  // guiBridgeHint rather than failing silently, since "permission not
  // granted yet" is an expected first-run state, not a bug.
  const WSJTX_MODE_BUTTON = { FT8: 'FT8', FT4: 'FT4', MSK144: 'MSK', Q65: 'Q65', JT65: 'JT65' };

  function guiButtonClick(name) {
    return postJson('/remote/gui/button', { name }).then(d => {
      if (!d.ok) { guiBridgeHint.textContent = d.error; guiBridgeHint.className = 'proc-hint err'; }
      return d;
    });
  }

  function guiSetCheckbox(el, name) {
    const wasChecked = el.checked;
    el.disabled = true;
    if (wasChecked) { guiBridgeHint.textContent = `Arming ${name}… (can take a few seconds)`; guiBridgeHint.className = 'proc-hint'; }
    return postJson('/remote/gui/checkbox', { name, on: wasChecked }).then(d => {
      el.disabled = false;
      if (!d.ok) {
        guiBridgeHint.textContent = d.error;
        guiBridgeHint.className = 'proc-hint err';
        el.checked = !wasChecked; // revert -- the click didn't actually take
      } else {
        guiBridgeHint.textContent = '';
        guiBridgeHint.className = 'proc-hint';
        el.checked = d.value;
      }
    }).catch(e => {
      el.disabled = false;
      el.checked = !wasChecked;
      guiBridgeHint.textContent = String(e);
      guiBridgeHint.className = 'proc-hint err';
    });
  }

  // -- Reduce power to a safe level before Tune engages (a real carrier at
  // full power into a mismatched/detuned antenna is the whole reason Tune
  // exists), then restore whatever it actually was before -- same helpers
  // as templates/live_entities.html's Find/Scan, duplicated here since
  // there's no shared JS module between pages in this app. Best-effort: if
  // reading the current power fails, skip both the reduce and the restore
  // rather than blocking Tune on it.
  const TUNE_POWER_WATTS = 10;
  let savedPowerWatts = null;

  async function reducePowerForTune() {
    savedPowerWatts = null;
    try {
      const status = await fetch('/radio/status').then(r => r.json());
      if (typeof status.rfpower_watts !== 'number') return;
      savedPowerWatts = status.rfpower_watts;
      if (Math.abs(savedPowerWatts - TUNE_POWER_WATTS) < 0.5) return; // already low enough
      const d = await postJson('/radio/power', { watts: TUNE_POWER_WATTS });
      if (!d.ok) savedPowerWatts = null; // didn't actually take -- nothing to restore later
    } catch (e) {
      savedPowerWatts = null;
    }
  }

  async function restorePowerAfterTune() {
    if (savedPowerWatts == null) return;
    try {
      await postJson('/radio/power', { watts: savedPowerWatts });
    } catch (e) {
      // best-effort
    }
    savedPowerWatts = null;
  }

  function pollGuiStatus() {
    fetch('/remote/gui/status').then(r => r.json()).then(d => {
      if (!d.ok) {
        guiBridgeHint.textContent = d.error;
        guiBridgeHint.className = 'proc-hint err';
        return;
      }
      guiBridgeHint.textContent = '';
      guiBridgeHint.className = 'proc-hint';
      const cb = d.checkboxes;
      const active = root.activeElement;
      if (active !== guiMonitor) guiMonitor.checked = cb['Monitor'];
      if (active !== guiDecode) guiDecode.checked = cb['Decode'];
      if (active !== guiEnableTx && !guiEnableTx.disabled) guiEnableTx.checked = cb['Enable Tx'];
      if (active !== guiTune && !guiTune.disabled) guiTune.checked = cb['Tune'];
    }).catch(() => {});
  }

  guiStopBtn.addEventListener('click', () => guiButtonClick('Stop'));
  guiMonitor.addEventListener('change', () => guiSetCheckbox(guiMonitor, 'Monitor'));
  guiDecode.addEventListener('change', () => guiSetCheckbox(guiDecode, 'Decode'));
  guiEnableTx.addEventListener('change', () => guiSetCheckbox(guiEnableTx, 'Enable Tx'));
  guiTune.addEventListener('change', async () => {
    const turningOn = guiTune.checked;
    if (turningOn) {
      guiBridgeHint.textContent = 'Lowering power for tune…';
      guiBridgeHint.className = 'proc-hint';
      await reducePowerForTune();
    }
    await guiSetCheckbox(guiTune, 'Tune');
    // Restore power once Tune is confirmed off, or immediately if turning
    // Tune on didn't actually take (guiSetCheckbox reverts the checkbox on
    // failure -- e.g. WSJT-X not running, no Accessibility permission --
    // in which case nothing was ever keyed and power shouldn't stay low).
    if (!guiTune.checked) await restorePowerAfterTune();
  });

  loadRemoteBandPresets();

  pollGuiStatus();
  const pollGuiId = setInterval(pollGuiStatus, 4000);

  modeStack.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => {
      modeStack.querySelectorAll('button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const wsjtxName = WSJTX_MODE_BUTTON[btn.dataset.mode];
      if (wsjtxName) guiButtonClick(wsjtxName);
    });
  });

  root.getElementById('ft-submit').addEventListener('click', () => {
    const text = root.getElementById('ft-text').value;
    const send = root.getElementById('ft-send').checked;
    const result = root.getElementById('ft-result');
    postJson('/remote/free_text', { text, send })
      .then(d => showResult(result, !d.error && d.ok, d.error || (d.ok ? 'Sent' : 'Not sent -- no known WSJT-X address yet')))
      .catch(e => showResult(result, false, String(e)));
  });

  root.getElementById('halt-btn').addEventListener('click', () => {
    postJson('/remote/halt_tx', { auto_tx_only: false }).catch(() => {});
  });

  root.getElementById('erase-btn').addEventListener('click', () => {
    // Clear locally right away for immediate feedback -- not certain WSJT-X
    // echoes its own Clear back out over UDP when *we* send it one (as
    // opposed to when the user clicks the real Erase button), so don't
    // rely on that round trip.
    bandBody.innerHTML = '';
    rxFreqBody.innerHTML = '';
    timeGroups.band.lastTime = timeGroups.rxfreq.lastTime = null;
    timeGroups.band.alt = timeGroups.rxfreq.alt = false;
    wf.clear();
    postJson('/remote/erase', { window: 0 }).catch(() => {});
  });

  root.getElementById('cfg-submit').addEventListener('click', () => {
    const result = root.getElementById('cfg-result');
    const activeMode = modeStack.querySelector('button.active');
    postJson('/remote/configure', {
      mode: activeMode ? activeMode.dataset.mode : 'FT8',
      tr_period: parseInt(root.getElementById('cfg-tr').value, 10) || 15,
      dx_call: root.getElementById('cfg-dxcall').value,
      dx_grid: root.getElementById('cfg-dxgrid').value,
      rx_df: parseInt(root.getElementById('cfg-rxdf').value, 10) || 1500,
      frequency_tolerance: parseInt(root.getElementById('cfg-tol').value, 10) || 10,
      fast_mode: root.getElementById('cfg-fast').checked,
      generate_messages: root.getElementById('cfg-genmsg').checked,
    })
      .then(d => showResult(result, !d.error && d.ok, d.error || (d.ok ? 'Sent' : 'Not sent')))
      .catch(e => showResult(result, false, String(e)));
  });

  // -- Log QSO: preview WSJT-X's current tracked exchange, let the operator
  // review/edit, then write it directly (see log_writer.py for why) --
  const logQsoOverlay = root.getElementById('log-qso-overlay');
  const logQsoError = root.getElementById('log-qso-error');
  const logQsoFields = ['mycall', 'mygrid', 'call', 'grid', 'mode', 'band', 'rstsent', 'rstrcvd', 'freq', 'dxcc', 'dxccid', 'cqzone', 'comments'];
  const logQsoFieldToKey = {
    mycall: 'my_call', mygrid: 'my_grid', call: 'call', grid: 'grid', mode: 'mode', band: 'band',
    rstsent: 'rst_sent', rstrcvd: 'rst_received', freq: 'tx_frequency_mhz',
    dxcc: 'dxcc_country', dxccid: 'dxcc_id', cqzone: 'cq_zone', comments: 'comments',
  };

  function openLogQso() {
    logQsoError.style.display = 'none';
    root.getElementById('log-qso-result').textContent = '';
    fetch('/remote/log_qso/preview').then(r => r.json()).then(data => {
      if (data.error) {
        logQsoError.textContent = data.error;
        logQsoError.style.display = 'block';
      }
      logQsoFields.forEach(f => {
        const key = logQsoFieldToKey[f];
        const val = data[key];
        root.getElementById('lq-' + f).value = (val === null || val === undefined) ? '' : val;
      });
      logQsoOverlay.style.display = 'flex';
    }).catch(e => {
      logQsoError.textContent = String(e);
      logQsoError.style.display = 'block';
      logQsoOverlay.style.display = 'flex';
    });
  }

  function submitToQueue() {
    const result = root.getElementById('log-qso-result');
    const body = {};
    logQsoFields.forEach(f => { body[logQsoFieldToKey[f]] = root.getElementById('lq-' + f).value; });
    postJson('/remote/qso_queue', body).then(d => {
      if (d.error) { showResult(result, false, d.error); return; }
      showResult(result, true, 'Added to queue');
      renderQueue(d.queue);
      setTimeout(() => { logQsoOverlay.style.display = 'none'; }, 900);
    }).catch(e => showResult(result, false, String(e)));
  }

  root.getElementById('log-qso-btn').addEventListener('click', openLogQso);
  root.getElementById('log-qso-cancel').addEventListener('click', () => { logQsoOverlay.style.display = 'none'; });
  root.getElementById('log-qso-confirm').addEventListener('click', submitToQueue);

  // -- Queued QSOs panel --
  const qsoQueueBody = root.getElementById('qso-queue-body');

  function fmtQueuedAt(epochS) {
    return fmtUtc(epochS);
  }

  function renderQueue(entries) {
    qsoQueueBody.innerHTML = '';
    entries.slice().reverse().forEach(e => {
      const tr = document.createElement('tr');
      const statusLabel = e.status === 'error' ? `error: ${e.error || ''}` : e.status;
      tr.innerHTML = `
        <td>${fmtQueuedAt(e.queued_at)}</td>
        <td>${e.call}</td>
        <td>${e.band}</td>
        <td>${e.mode}</td>
        <td>${statusLabel}</td>
        <td></td>
      `;
      const actionCell = tr.lastElementChild;
      if (e.status !== 'sent') {
        const sendBtn = document.createElement('button');
        sendBtn.textContent = 'Send';
        sendBtn.addEventListener('click', () => sendQueueEntry(e.id));
        actionCell.appendChild(sendBtn);
      }
      const delBtn = document.createElement('button');
      delBtn.textContent = 'Delete';
      delBtn.style.marginLeft = '0.3rem';
      delBtn.addEventListener('click', () => deleteQueueEntry(e.id));
      actionCell.appendChild(delBtn);
      qsoQueueBody.appendChild(tr);
    });
  }

  function loadQueue() {
    fetch('/remote/qso_queue').then(r => r.json()).then(d => renderQueue(d.queue || [])).catch(() => {});
  }

  function sendQueueEntry(id, force) {
    postJson(`/remote/qso_queue/${id}/send`, { force: !!force }).then(d => {
      if (d.error === 'possible_duplicate') {
        if (confirm('A QSO with this call/band/mode was already logged recently -- possible duplicate. Send anyway?')) {
          sendQueueEntry(id, true);
        }
        return;
      }
      if (!d.ok) alert('Failed to send to MacLoggerDX: ' + (d.message || d.error || 'unknown error'));
      loadQueue();
    }).catch(e => alert('Failed to send: ' + e));
  }

  function deleteQueueEntry(id) {
    postJson(`/remote/qso_queue/${id}/delete`, {}).then(d => renderQueue(d.queue || [])).catch(() => {});
  }

  const queueBatchResult = root.getElementById('queue-batch-result');

  root.getElementById('queue-send-all').addEventListener('click', () => {
    queueBatchResult.textContent = 'Sending…';
    queueBatchResult.className = 'action-result';
    postJson('/remote/qso_queue/send_all', {}).then(d => {
      const results = d.results || [];
      const sent = results.filter(r => r.ok).length;
      const dups = results.filter(r => r.error === 'possible_duplicate').length;
      const failed = results.length - sent - dups;
      let msg = `${sent} sent`;
      if (dups) msg += `, ${dups} skipped (possible duplicate -- send individually to override)`;
      if (failed) msg += `, ${failed} failed`;
      if (!results.length) msg = 'Nothing pending';
      queueBatchResult.textContent = msg;
      queueBatchResult.className = 'action-result ' + (failed ? 'err' : 'ok');
      renderQueue(d.queue || []);
    }).catch(e => { queueBatchResult.textContent = String(e); queueBatchResult.className = 'action-result err'; });
  });

  root.getElementById('queue-clear-sent').addEventListener('click', () => {
    postJson('/remote/qso_queue/clear_sent', {}).then(d => renderQueue(d.queue || [])).catch(() => {});
  });

  loadQueue();

  return function unmount() {
    unsubs.forEach(fn => fn());
    clearInterval(pollGuiId);
    wf.stopAutoFit();
    spectrum.stopAutoFit();
    if (spectrumSubscribed) { ctx.unlistenSpectrum(); spectrumSubscribed = false; }
  };
}

// -- Standalone feed adapter: same {on, send, onStatus, listenSpectrum,
// unlistenSpectrum} shape as static/dashboard_live.js's
// createDashboardLiveFeed() (and static/live_monitor.js's near-identical
// copy) -- used by the document-rooted cases below (the full page and each
// standalone widget route still get their own connection; only the
// Dashboard-applet case shares one). Kept local to this file for the same
// reason live_monitor.js keeps its own copy: nothing shares a JS module
// between pages in this app yet.
function createOwnWebSocketFeedAdapterForRemote() {
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

// -- Registration for the Dashboard applet loader -- harmless to define
// even when this file is loaded by a real page navigation below, it just
// adds four entries to a registry nothing looks at outside /dashboard.
window.DashboardApplets = window.DashboardApplets || {};
['band_activity', 'rx_freq', 'waterfall', 'rest'].forEach(mode => {
  window.DashboardApplets['remote_' + mode] = {
    mount(root, ctx) { return mountWsjtxRemote(root, ctx, mode); },
  };
});

// -- Auto-bootstrap for real page navigations only: the full /remote page
// and the four standalone /remote/widget/* routes all load this same file
// via a normal <script src> tag and expect it to just run, exactly as
// before this refactor. Guarded on rconn-dot actually existing in
// `document` so that dashboard.html loading this file purely to populate
// the registry above (its own top-level document has none of these ids)
// no-ops harmlessly instead of throwing on null element lookups.
if (document.getElementById('rconn-dot')) {
  mountWsjtxRemote(document, createOwnWebSocketFeedAdapterForRemote(), document.body.dataset.widgetMode || null);
}

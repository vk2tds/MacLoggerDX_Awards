// radio_control.js -- Radio Control's page logic, shared between the full
// page (templates/radio.html), its three standalone Dashboard widget routes
// (templates/radio_widget.html, /radio/widget/control|proc|freq), and --
// as of the JS-applet migration, see
// /Users/darryl/.claude/plans/crystalline-bouncing-meteor.md -- the same
// three widgets mounted directly as shadow-DOM applets on the /dashboard
// page itself.
//
// mountRadioControl(root, ctx, widgetMode) is the one implementation used by
// all of these -- same shape as static/live_monitor.js's mountLiveMonitor()
// (see its header comment for the full root/ctx/widgetMode contract). This
// family has no WebSocket dependency at all (rigctld status is plain REST
// polling, not a live feed), so `ctx` is accepted only for signature
// consistency with the other families and isn't otherwise used.
function mountRadioControl(root, ctx, widgetMode) {
  if (root.host) root.host.setAttribute('data-widget-mode', widgetMode || '');

  const connDot = root.getElementById('conn-dot');
  const connText = root.getElementById('conn-text');
  const freqVal = root.getElementById('freq-val');
  const modeVal = root.getElementById('mode-val');
  const bandVal = root.getElementById('band-val');
  const freqInput = root.getElementById('freq-input');
  const freqSetBtn = root.getElementById('freq-set-btn');
  const freqResult = root.getElementById('freq-result');
  const modeRow = root.getElementById('mode-row');
  const modeResult = root.getElementById('mode-result');
  const bandRow = root.getElementById('band-row');
  const pttBtn = root.getElementById('ptt-btn');
  const pttResult = root.getElementById('ptt-result');
  const smeterFill = root.getElementById('smeter-fill');
  const smeterLabel = root.getElementById('smeter-label');
  const ritInput = root.getElementById('rit-input');
  const ritSetBtn = root.getElementById('rit-set-btn');
  const ritClearBtn = root.getElementById('rit-clear-btn');
  const ritResult = root.getElementById('rit-result');
  const xitInput = root.getElementById('xit-input');
  const xitSetBtn = root.getElementById('xit-set-btn');
  const xitClearBtn = root.getElementById('xit-clear-btn');
  const xitResult = root.getElementById('xit-result');
  const powerInput = root.getElementById('power-input');
  const powerSetBtn = root.getElementById('power-set-btn');
  const powerReadout = root.getElementById('power-readout');
  const powerResult = root.getElementById('power-result');

  let pttState = false;
  let freqFocused = false;
  freqInput.addEventListener('focus', () => { freqFocused = true; });
  freqInput.addEventListener('blur', () => { freqFocused = false; });
  let ritFocused = false;
  ritInput.addEventListener('focus', () => { ritFocused = true; });
  ritInput.addEventListener('blur', () => { ritFocused = false; });
  let xitFocused = false;
  xitInput.addEventListener('focus', () => { xitFocused = true; });
  xitInput.addEventListener('blur', () => { xitFocused = false; });
  let powerFocused = false;
  powerInput.addEventListener('focus', () => { powerFocused = true; });
  powerInput.addEventListener('blur', () => { powerFocused = false; });

  // Hamlib S-meter values are dBS: 0 = S9, ~6dB per S-unit below that. Not
  // standardized above S9 -- shown as "S9+NdB" there, per common convention.
  function sMeterInfo(dbs) {
    if (dbs === null || dbs === undefined) return { label: 'S-meter: --', pct: 0 };
    const sUnit = 9 + dbs / 6;
    const label = sUnit <= 9 ? `S${Math.max(0, Math.round(sUnit))}` : `S9+${Math.round(dbs)}dB`;
    const pct = Math.max(0, Math.min(100, ((dbs + 54) / 114) * 100));
    return { label: `S-meter: ${label} (${Math.round(dbs)} dBS)`, pct };
  }

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

  function renderStatus(s) {
    if (!s.connected) {
      connDot.className = 'dot down';
      connText.textContent = s.error || 'Not connected';
      connText.className = 'err';
      return;
    }
    connDot.className = 'dot up';
    connText.textContent = s.error ? s.error : 'connected';
    connText.className = s.error ? 'err' : '';
    if (s.error) return;

    freqVal.textContent = (s.frequency_hz / 1e6).toFixed(6);
    if (!freqFocused) freqInput.value = (s.frequency_hz / 1e6).toFixed(6);
    modeVal.textContent = s.mode || '--';
    bandVal.textContent = s.band || '--';

    bandRow.querySelectorAll('button').forEach(b => b.classList.toggle('current', b.dataset.band === s.band));
    modeRow.querySelectorAll('button').forEach(b => b.classList.toggle('current', b.dataset.mode === s.mode));

    pttState = !!s.ptt;
    pttBtn.textContent = pttState ? 'Unkey Tx' : 'Key Tx';
    pttBtn.classList.toggle('keyed', pttState);

    const meter = sMeterInfo(s.strength_dbs);
    smeterFill.style.width = meter.pct + '%';
    smeterLabel.textContent = s.strength_error ? 'S-meter: unavailable' : meter.label;

    if (!ritFocused) ritInput.value = s.rit_hz ?? 0;
    if (!xitFocused) xitInput.value = s.xit_hz ?? 0;
    if (s.rfpower_watts !== null && s.rfpower_watts !== undefined) {
      if (!powerFocused) powerInput.value = Math.round(s.rfpower_watts);
      powerReadout.textContent = `(${Math.round(s.rfpower_fraction * 100)}% of max)`;
    } else {
      powerReadout.textContent = s.rfpower_error ? 'unavailable' : '';
    }
  }

  function poll() {
    fetch('/radio/status').then(r => r.json()).then(renderStatus).catch(err => {
      connDot.className = 'dot down';
      connText.textContent = String(err);
      connText.className = 'err';
    });
  }

  freqSetBtn.addEventListener('click', () => {
    const mhz = parseFloat(freqInput.value);
    if (!isFinite(mhz) || mhz <= 0) { showResult(freqResult, false, 'Enter a frequency in MHz'); return; }
    postJson('/radio/frequency', { frequency_hz: mhz * 1e6 })
      .then(d => showResult(freqResult, d.ok, d.ok ? 'Sent' : d.error))
      .catch(e => showResult(freqResult, false, String(e)));
  });

  modeRow.querySelectorAll('button[data-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      postJson('/radio/mode', { mode: btn.dataset.mode, passband: 0 })
        .then(d => showResult(modeResult, d.ok, d.ok ? 'Sent' : d.error))
        .catch(e => showResult(modeResult, false, String(e)));
    });
  });

  bandRow.querySelectorAll('button[data-band]').forEach(btn => {
    btn.addEventListener('click', () => {
      postJson('/radio/band/' + encodeURIComponent(btn.dataset.band), {})
        .then(d => showResult(freqResult, d.ok, d.ok ? 'QSY sent' : d.error))
        .catch(e => showResult(freqResult, false, String(e)));
    });
  });

  pttBtn.addEventListener('click', () => {
    postJson('/radio/ptt', { on: !pttState })
      .then(d => showResult(pttResult, d.ok, d.ok ? 'OK' : d.error))
      .catch(e => showResult(pttResult, false, String(e)));
  });

  function setRit(hz) {
    postJson('/radio/rit', { hz })
      .then(d => showResult(ritResult, d.ok, d.ok ? 'Sent' : d.error))
      .catch(e => showResult(ritResult, false, String(e)));
  }
  ritSetBtn.addEventListener('click', () => setRit(parseInt(ritInput.value, 10) || 0));
  ritClearBtn.addEventListener('click', () => { ritInput.value = 0; setRit(0); });

  function setXit(hz) {
    postJson('/radio/xit', { hz })
      .then(d => showResult(xitResult, d.ok, d.ok ? 'Sent' : d.error))
      .catch(e => showResult(xitResult, false, String(e)));
  }
  xitSetBtn.addEventListener('click', () => setXit(parseInt(xitInput.value, 10) || 0));
  xitClearBtn.addEventListener('click', () => { xitInput.value = 0; setXit(0); });

  powerSetBtn.addEventListener('click', () => {
    const watts = parseFloat(powerInput.value);
    if (!isFinite(watts) || watts < 0) { showResult(powerResult, false, 'Enter power in watts'); return; }
    postJson('/radio/power', { watts })
      .then(d => showResult(powerResult, d.ok, d.ok ? 'Sent' : d.error))
      .catch(e => showResult(powerResult, false, String(e)));
  });

  poll();
  const pollId = setInterval(poll, 1000);

  // -- rigctld process management --
  const procDot = root.getElementById('proc-dot');
  const procText = root.getElementById('proc-text');
  const procStartBtn = root.getElementById('proc-start-btn');
  const procStopBtn = root.getElementById('proc-stop-btn');
  const procRestartBtn = root.getElementById('proc-restart-btn');
  const procActionResult = root.getElementById('proc-action-result');
  const procRigModel = root.getElementById('proc-rig-model');
  const procDevice = root.getElementById('proc-device');
  const procDeviceList = root.getElementById('proc-device-list');
  const procBaud = root.getElementById('proc-baud');
  const procHost = root.getElementById('proc-host');
  const procPort = root.getElementById('proc-port');
  const procExtra = root.getElementById('proc-extra');
  const procBinary = root.getElementById('proc-binary');
  const procSaveBtn = root.getElementById('proc-save-btn');
  const procSaveResult = root.getElementById('proc-save-result');
  const procLogDetails = root.getElementById('proc-log-details');
  const procLog = root.getElementById('proc-log');

  function loadRigModels() {
    fetch('/radio/process/rig_models').then(r => r.json()).then(d => {
      const models = d.models || [];
      const byMfg = {};
      models.forEach(m => { (byMfg[m.mfg] = byMfg[m.mfg] || []).push(m); });
      const mfgs = Object.keys(byMfg).sort();
      let html = '<option value="">-- select --</option>';
      mfgs.forEach(mfg => {
        html += `<optgroup label="${mfg}">`;
        byMfg[mfg].sort((a, b) => a.model.localeCompare(b.model)).forEach(m => {
          html += `<option value="${m.id}">${m.model} (${m.id})</option>`;
        });
        html += '</optgroup>';
      });
      procRigModel.innerHTML = html;
      loadProcConfig();
    }).catch(() => { procRigModel.innerHTML = '<option value="">(failed to load)</option>'; });
  }

  function loadSerialDevices() {
    fetch('/radio/process/serial_devices').then(r => r.json()).then(d => {
      procDeviceList.innerHTML = (d.devices || []).map(dev => `<option value="${dev}">`).join('');
    }).catch(() => {});
  }

  function loadProcConfig() {
    fetch('/radio/process/config').then(r => r.json()).then(cfg => {
      procRigModel.value = cfg.rig_model || '';
      procDevice.value = cfg.device || '';
      procBaud.value = cfg.baud || '';
      procHost.value = cfg.listen_host || '127.0.0.1';
      procPort.value = cfg.listen_port || 4532;
      procExtra.value = cfg.extra_args || '';
      procBinary.value = cfg.binary_path || '';
    }).catch(() => {});
  }

  function buildProcConfigBody() {
    return {
      rig_model: procRigModel.value, device: procDevice.value.trim(), baud: procBaud.value.trim(),
      listen_host: procHost.value.trim(), listen_port: procPort.value.trim(),
      extra_args: procExtra.value.trim(), binary_path: procBinary.value.trim(),
    };
  }

  function saveProcConfig() {
    return postJson('/radio/process/config', buildProcConfigBody());
  }

  procSaveBtn.addEventListener('click', () => {
    saveProcConfig()
      .then(d => showResult(procSaveResult, d.ok, d.ok ? 'Saved' : d.error))
      .catch(e => showResult(procSaveResult, false, String(e)));
  });

  function renderProcStatus(s) {
    if (s.managed_running) {
      procDot.className = 'dot up';
      procText.textContent = `Running (PID ${s.managed_pid}, started by this app)`;
    } else if (s.external_running) {
      procDot.className = 'dot up';
      procText.textContent = 'Running (started outside this app -- Stop/Restart unavailable)';
    } else if (s.watchdog_enabled) {
      procDot.className = 'dot down';
      procText.textContent = 'Not running -- watchdog will auto-restart it shortly';
    } else {
      procDot.className = 'dot down';
      procText.textContent = s.binary_path ? 'Not running' : 'Not running -- rigctld binary not found (install Hamlib)';
    }
    procStopBtn.disabled = !s.managed_running;
    procRestartBtn.disabled = !s.managed_running;
    procStartBtn.disabled = s.managed_running || s.external_running;
  }

  function pollProcStatus() {
    fetch('/radio/process/status').then(r => r.json()).then(renderProcStatus).catch(() => {});
  }

  function refreshProcLog() {
    fetch('/radio/process/log').then(r => r.json()).then(d => { procLog.textContent = d.log || '(empty)'; }).catch(() => {});
  }
  procLogDetails.addEventListener('toggle', () => { if (procLogDetails.open) refreshProcLog(); });

  procStartBtn.addEventListener('click', () => {
    procStartBtn.disabled = true;
    // Save whatever's currently in the form first -- Start should reflect
    // what's on screen, not require a separate Save Config click beforehand.
    saveProcConfig().then(saveResult => {
      if (!saveResult.ok) {
        showResult(procActionResult, false, 'Config not saved: ' + saveResult.error);
        pollProcStatus();
        return;
      }
      return postJson('/radio/process/start', {}).then(d => {
        showResult(procActionResult, d.ok, d.message);
        pollProcStatus();
        if (procLogDetails.open) refreshProcLog();
      });
    }).catch(e => showResult(procActionResult, false, String(e)));
  });

  procStopBtn.addEventListener('click', () => {
    postJson('/radio/process/stop', {}).then(d => {
      showResult(procActionResult, d.ok, d.message);
      pollProcStatus();
    }).catch(e => showResult(procActionResult, false, String(e)));
  });

  procRestartBtn.addEventListener('click', () => {
    saveProcConfig().then(saveResult => {
      if (!saveResult.ok) {
        showResult(procActionResult, false, 'Config not saved: ' + saveResult.error);
        pollProcStatus();
        return;
      }
      return postJson('/radio/process/restart', {}).then(d => {
        showResult(procActionResult, d.ok, d.message);
        pollProcStatus();
        if (procLogDetails.open) refreshProcLog();
      });
    }).catch(e => showResult(procActionResult, false, String(e)));
  });

  loadRigModels();
  loadSerialDevices();
  pollProcStatus();
  const procPollId = setInterval(pollProcStatus, 2000);

  return function unmount() {
    clearInterval(pollId);
    clearInterval(procPollId);
  };
}

// -- Registration for the Dashboard applet loader -- see
// static/live_monitor.js's near-identical comment for how this coexists
// with a real page navigation below.
window.DashboardApplets = window.DashboardApplets || {};
['control', 'proc', 'freq'].forEach(mode => {
  window.DashboardApplets['radio_' + mode] = {
    mount(root, ctx) { return mountRadioControl(root, ctx, mode); },
  };
});

// -- Auto-bootstrap for real page navigations only: the full /radio page and
// the three standalone /radio/widget/* routes all load this same file via a
// normal <script src> tag and expect it to just run. Guarded on conn-dot
// actually existing in `document` so dashboard.html loading this file purely
// to populate the registry above no-ops harmlessly instead of throwing on
// null element lookups.
if (document.getElementById('conn-dot')) {
  mountRadioControl(document, null, document.body.dataset.widgetMode || null);
}

// frequencies.js -- Frequencies' page logic, shared between the full page
// (templates/frequencies.html), its Dashboard widget route
// (templates/frequencies_widget.html, /frequencies/widget), and -- as of
// the JS-applet migration, see
// /Users/darryl/.claude/plans/crystalline-bouncing-meteor.md -- the same
// widget mounted directly as a shadow-DOM applet on the /dashboard page
// itself. Single scrolling screen, no sub-sections, so no widgetMode
// parameter/CSS mode-switching here.
//
// mountFrequencies(root, ctx) -- same root/ctx contract as
// static/live_monitor.js's mountLiveMonitor() (see its header comment),
// though this family has no WebSocket dependency (presets are REST
// polling) so `ctx` is accepted only for signature consistency and isn't
// otherwise used.
function mountFrequencies(root, ctx) {
  if (root.host) root.host.setAttribute('data-widget-mode', '');

  const presetRows = root.getElementById('fq-preset-rows');
  const newName = root.getElementById('fq-new-name');
  const newFreq = root.getElementById('fq-new-freq');
  const addBtn = root.getElementById('fq-add-btn');
  const presetResult = root.getElementById('fq-preset-result');

  const USED_BY_KEYS = ['remote', 'find', 'radio', 'rigdial'];

  let presetsFocused = false;

  function postJson(url, body) {
    return fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
    }).then(r => r.json());
  }

  function showResult(el, ok, msg) {
    el.textContent = msg || (ok ? 'OK' : 'Failed');
    el.className = 'action-result ' + (ok ? 'ok' : 'err');
    setTimeout(() => { el.textContent = ''; }, 4000);
  }

  // Same band table used elsewhere (Remote tab, DX Monitor) for a display
  // hint -- server is authoritative for actual control.
  const BAND_TABLE = [
    [1.8, 2.0, '160M'], [3.5, 4.0, '80M'], [5.3, 5.4, '60M'], [7.0, 7.3, '40M'],
    [10.1, 10.15, '30M'], [14.0, 14.35, '20M'], [18.068, 18.168, '17M'],
    [21.0, 21.45, '15M'], [24.89, 24.99, '12M'], [28.0, 29.7, '10M'],
    [50.0, 54.0, '6M'], [70.0, 70.5, '4M'], [144.0, 148.0, '2M'],
  ];
  function bandFor(hz) {
    const mhz = hz / 1e6;
    for (const [lo, hi, name] of BAND_TABLE) if (mhz >= lo && mhz <= hi) return name;
    return '--';
  }

  function renderPresets(presets) {
    if (presetsFocused) return;
    presetRows.innerHTML = '';
    presets.forEach(p => {
      const tr = document.createElement('tr');

      const nameTd = document.createElement('td');
      const nameInput = document.createElement('input');
      nameInput.type = 'text'; nameInput.value = p.name;
      nameInput.addEventListener('focus', () => { presetsFocused = true; });
      nameInput.addEventListener('blur', () => {
        presetsFocused = false;
        if (nameInput.value.trim() && nameInput.value.trim() !== p.name) {
          postJson(`/frequencies/presets/${p.id}`, { name: nameInput.value.trim() })
            .then(d => showResult(presetResult, d.ok, d.ok ? 'Saved' : d.error))
            .catch(e => showResult(presetResult, false, String(e)));
        }
      });
      nameTd.appendChild(nameInput);

      const freqTd = document.createElement('td');
      const freqInput = document.createElement('input');
      freqInput.type = 'text'; freqInput.className = 'freq';
      freqInput.value = (p.freq_hz / 1e6).toFixed(6);
      freqInput.addEventListener('focus', () => { presetsFocused = true; });
      freqInput.addEventListener('blur', () => {
        presetsFocused = false;
        const mhz = parseFloat(freqInput.value);
        if (isFinite(mhz) && mhz > 0 && Math.round(mhz * 1e6) !== p.freq_hz) {
          postJson(`/frequencies/presets/${p.id}`, { freq_hz: mhz * 1e6 })
            .then(d => showResult(presetResult, d.ok, d.ok ? 'Saved' : d.error))
            .catch(e => showResult(presetResult, false, String(e)));
        }
      });
      freqTd.appendChild(freqInput);

      const bandTd = document.createElement('td');
      bandTd.className = 'band';
      bandTd.textContent = bandFor(p.freq_hz);

      tr.append(nameTd, freqTd, bandTd);

      USED_BY_KEYS.forEach(key => {
        const td = document.createElement('td');
        td.className = 'check';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = !!p[key];
        cb.addEventListener('change', () => {
          postJson(`/frequencies/presets/${p.id}`, { [key]: cb.checked })
            .then(d => { if (!d.ok) { cb.checked = !cb.checked; showResult(presetResult, false, d.error); } })
            .catch(e => { cb.checked = !cb.checked; showResult(presetResult, false, String(e)); });
        });
        td.appendChild(cb);
        tr.appendChild(td);
      });

      const applyTd = document.createElement('td');
      const applyBtn = document.createElement('button');
      applyBtn.textContent = 'Set Now';
      applyBtn.addEventListener('click', () => {
        postJson(`/frequencies/presets/${p.id}/apply`, {})
          .then(d => showResult(presetResult, d.ok, d.ok ? `Tuned to ${p.name}` : d.error))
          .catch(e => showResult(presetResult, false, String(e)));
      });
      applyTd.appendChild(applyBtn);

      const delTd = document.createElement('td');
      const delBtn = document.createElement('button');
      delBtn.textContent = 'Delete'; delBtn.className = 'danger';
      delBtn.addEventListener('click', () => {
        postJson(`/frequencies/presets/${p.id}/delete`, {})
          .then(() => loadPresets())
          .catch(e => showResult(presetResult, false, String(e)));
      });
      delTd.appendChild(delBtn);

      tr.append(applyTd, delTd);
      presetRows.appendChild(tr);
    });
  }

  addBtn.addEventListener('click', () => {
    const name = newName.value.trim();
    const mhz = parseFloat(newFreq.value);
    if (!name) { showResult(presetResult, false, 'Enter a name'); return; }
    if (!isFinite(mhz) || mhz <= 0) { showResult(presetResult, false, 'Enter a frequency in MHz'); return; }
    postJson('/frequencies/presets', { name, freq_hz: mhz * 1e6 }).then(d => {
      if (d.ok) { newName.value = ''; newFreq.value = ''; loadPresets(); }
      showResult(presetResult, d.ok, d.ok ? 'Added' : d.error);
    }).catch(e => showResult(presetResult, false, String(e)));
  });

  function loadPresets() {
    fetch('/frequencies/presets').then(r => r.json()).then(d => renderPresets(d.presets || []))
      .catch(e => showResult(presetResult, false, String(e)));
  }

  loadPresets();
  const pollId = setInterval(loadPresets, 2000);

  return function unmount() {
    clearInterval(pollId);
  };
}

// -- Registration for the Dashboard applet loader. See
// static/live_monitor.js's near-identical comment for how this coexists
// with a real page navigation below.
window.DashboardApplets = window.DashboardApplets || {};
window.DashboardApplets['frequencies'] = {
  mount(root, ctx) { return mountFrequencies(root, ctx); },
};

// -- Auto-bootstrap for a real page navigation (the full /frequencies page
// or the standalone /frequencies/widget route) -- see
// static/live_monitor.js's near-identical note for why this guard is
// needed.
if (document.getElementById('fq-preset-rows')) {
  mountFrequencies(document, null);
}

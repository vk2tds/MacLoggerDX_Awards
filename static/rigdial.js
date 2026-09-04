// rigdial.js -- RigDial's page logic, shared between the full page
// (templates/rigdial.html), its Dashboard widget route
// (templates/rigdial_widget.html, /rigdial/widget), and -- as of the
// JS-applet migration, see
// /Users/darryl/.claude/plans/crystalline-bouncing-meteor.md -- the same
// widget mounted directly as a shadow-DOM applet on the /dashboard page
// itself. Single scrolling screen, no sub-sections, so no widgetMode
// parameter/CSS mode-switching here -- every context renders the whole
// thing, just in a smaller shell for the widget/applet cases.
//
// mountRigDial(root, ctx) -- same root/ctx contract as
// static/live_monitor.js's mountLiveMonitor() (see its header comment),
// though this family has no WebSocket dependency (rigdial status is REST
// polling) so `ctx` is accepted only for signature consistency and isn't
// otherwise used.
function mountRigDial(root, ctx) {
  if (root.host) root.host.setAttribute('data-widget-mode', '');

  const rdDot = root.getElementById('rd-dot');
  const rdConnText = root.getElementById('rd-conn-text');
  const rdEvent = root.getElementById('rd-event');
  const buttonRows = root.getElementById('rd-button-rows');
  const shuttleSelect = root.getElementById('rd-shuttle-action');
  const stepSmall = root.getElementById('rd-step-small');
  const stepBig = root.getElementById('rd-step-big');
  const saveConfigBtn = root.getElementById('rd-save-config-btn');
  const configResult = root.getElementById('rd-config-result');

  let configFocused = false;
  let pollId = null;

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

  // -- button mapping rows, built once meta is known. Fetched fresh every
  // mount rather than relying on window.RIGDIAL_BUTTON_ACTIONS/_COUNT (set
  // by an inline <script> for the full-page/standalone-widget case, see
  // app.py's /rigdial/meta docstring for why a shadow-mounted applet can't
  // rely on that same <script> having run). --
  function buildButtonRows(buttonActions, buttonCount) {
    for (let i = 0; i < buttonCount; i++) {
      const row = document.createElement('div');
      row.className = 'rd-row';
      const label = document.createElement('label');
      label.textContent = `Button ${i + 1}`;
      const select = document.createElement('select');
      select.id = `rd-button-${i}`;
      buttonActions.forEach(a => {
        const opt = document.createElement('option');
        opt.value = a; opt.textContent = a;
        select.appendChild(opt);
      });
      select.addEventListener('focus', () => { configFocused = true; });
      select.addEventListener('blur', () => { configFocused = false; });
      label.appendChild(select);
      row.appendChild(label);
      buttonRows.appendChild(row);
    }
  }

  shuttleSelect.addEventListener('focus', () => { configFocused = true; });
  shuttleSelect.addEventListener('blur', () => { configFocused = false; });
  stepSmall.addEventListener('focus', () => { configFocused = true; });
  stepSmall.addEventListener('blur', () => { configFocused = false; });
  stepBig.addEventListener('focus', () => { configFocused = true; });
  stepBig.addEventListener('blur', () => { configFocused = false; });

  function renderConfig(cfg, buttonCount) {
    if (configFocused) return;
    for (let i = 0; i < buttonCount; i++) {
      const select = root.getElementById(`rd-button-${i}`);
      select.value = (cfg.button_actions && cfg.button_actions[String(i)]) || 'none';
    }
    shuttleSelect.value = cfg.shuttle_action || 'none';
    stepSmall.value = cfg.jog_step_small_hz ?? 10;
    stepBig.value = cfg.jog_step_big_hz ?? 1000;
  }

  function renderStatus(s, buttonCount) {
    if (s.connected) {
      rdDot.className = 'dot up';
      rdConnText.textContent = 'ShuttleXpress connected';
    } else if (s.hid_available === false) {
      rdDot.className = 'dot down';
      rdConnText.textContent = 'hid package/native library not available -- see the note above';
    } else {
      rdDot.className = 'dot down';
      rdConnText.textContent = 'Not connected -- plug in the dial';
    }
    rdEvent.textContent = s.last_event ? `Last event: ${s.last_event}` : 'Last event: --';
    renderConfig(s.config || {}, buttonCount);
  }

  return fetch('/rigdial/meta').then(r => r.json()).then(meta => {
    const buttonCount = meta.button_count;
    buildButtonRows(meta.button_actions, buttonCount);

    saveConfigBtn.addEventListener('click', () => {
      const button_actions = {};
      for (let i = 0; i < buttonCount; i++) {
        button_actions[String(i)] = root.getElementById(`rd-button-${i}`).value;
      }
      postJson('/rigdial/config', {
        button_actions, shuttle_action: shuttleSelect.value,
        jog_step_small_hz: parseFloat(stepSmall.value) || 10,
        jog_step_big_hz: parseFloat(stepBig.value) || 1000,
      }).then(d => showResult(configResult, d.ok, d.ok ? 'Saved' : d.error))
        .catch(e => showResult(configResult, false, String(e)));
    });

    function pollStatus() {
      fetch('/rigdial/status').then(r => r.json()).then(s => renderStatus(s, buttonCount)).catch(err => {
        rdDot.className = 'dot down';
        rdConnText.textContent = String(err);
      });
    }

    pollStatus();
    pollId = setInterval(pollStatus, 1000);

    return function unmount() {
      clearInterval(pollId);
    };
  });
}

// -- Registration for the Dashboard applet loader. Unlike every other
// family, mount() here is async (it awaits the /rigdial/meta fetch before
// building the button rows) -- dashboard.html's mountApplet() already
// awaits applet.mount(...)'s return value before storing it as _unmount, so
// returning a Promise<unmount> instead of unmount directly works
// unchanged.
window.DashboardApplets = window.DashboardApplets || {};
window.DashboardApplets['rigdial'] = {
  mount(root, ctx) { return mountRigDial(root, ctx); },
};

// -- Auto-bootstrap for a real page navigation (the full /rigdial page or
// the standalone /rigdial/widget route) -- see static/live_monitor.js's
// near-identical note for why this guard is needed.
if (document.getElementById('rd-dot')) {
  mountRigDial(document, null);
}

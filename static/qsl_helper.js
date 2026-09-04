// qsl_helper.js -- QSL Helper's page logic, shared between the full page
// (templates/qsl_helper.html), its Dashboard widget route
// (templates/qsl_helper_widget.html, /qsl/widget), and -- as of the
// JS-applet migration, see
// /Users/darryl/.claude/plans/crystalline-bouncing-meteor.md -- the same
// widget mounted directly as a shadow-DOM applet on the /dashboard page
// itself. Single scrolling screen, no sub-sections, so no widgetMode
// parameter/CSS mode-switching here.
//
// mountQslHelper(root, ctx) -- same root/ctx contract as
// static/live_monitor.js's mountLiveMonitor() (see its header comment),
// though this family has no WebSocket dependency (everything here is REST
// polling) so `ctx` is accepted only for signature consistency and isn't
// otherwise used.
function mountQslHelper(root, ctx) {
  if (root.host) root.host.setAttribute('data-widget-mode', '');

  const content = root.getElementById('content');
  const cacheDot = root.getElementById('cache-dot');
  const cacheText = root.getElementById('cache-text');
  const reindexBtn = root.getElementById('reindex-btn');
  const lotwText = root.getElementById('lotw-text');
  const lotwUpdateBtn = root.getElementById('lotw-update-btn');
  const notInLogContent = root.getElementById('not-in-log-content');

  const METHODS = ['Direct', 'Bureau', 'OQRS', 'Club Log', 'eQSL', 'Other'];

  function qrzLink(call) {
    return `<a class="qrz-link" href="https://www.qrz.com/db/${encodeURIComponent(call)}" target="_blank" rel="noopener">QRZ</a>`;
  }

  function fmtBytes(n) {
    if (!n) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return n.toFixed(1) + ' ' + units[i];
  }

  function fmtUtc(epochS) {
    if (!epochS) return null;
    const d = new Date(epochS * 1000);
    const p = n => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
           `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
  }

  function renderCacheStatus(status) {
    cacheDot.className = 'cache-dot ' + (status.state || '');
    if (status.error) {
      cacheText.textContent = status.error;
      return;
    }
    const pct = status.file_size ? Math.round(100 * status.bytes_indexed / status.file_size) : 0;
    const when = fmtUtc(status.last_sync) || 'never';
    cacheText.textContent = `${status.state} -- ${fmtBytes(status.bytes_indexed)} / ${fmtBytes(status.file_size)} (${pct}%), last synced ${when}`;
  }

  function renderLotwStatus(status) {
    if (!status || !status.count) {
      lotwText.textContent = 'LoTW activity: not loaded';
      return;
    }
    const when = fmtUtc(status.updated) || 'unknown';
    lotwText.textContent = `LoTW activity: ${status.count.toLocaleString()} calls, updated ${when}`;
  }

  function markNotInLog(q) {
    fetch('/qsl/not_in_log', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        call: q.call, band: q.band, mode: q.mode, qso_start: q.qso_start,
        dxcc_country: q.dxcc_country, qso_start_str: q.qso_start_str,
      }),
    }).then(r => r.json()).then(() => load());
  }

  function undoNotInLog(key) {
    fetch('/qsl/not_in_log/undo', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key }),
    }).then(r => r.json()).then(() => load());
  }

  // Same (call, band, mode, qso_start) shape as qsl_helper.py's own
  // not_in_log_key() -- computed client-side so the detail row's own
  // toggle button (below) can mark/undo in place without needing the
  // server's freshly-generated entry list round-tripped back first.
  function notInLogKeyFor(q) {
    return `${(q.call || '').toUpperCase()}|${q.band || ''}|${q.mode || ''}|${q.qso_start || ''}`;
  }

  // The at-risk detail table's own "Not in their log" button, distinct
  // from the bottom summary list's Undo button above -- this one toggles
  // in place (mark <-> undo) instead of forcing a full reload, so the row
  // stays right where the operator was looking instead of vanishing the
  // instant it's clicked (it *will* still disappear on the next real page
  // load, same as before -- this only changes what happens in this same
  // session before that).
  function markNotInLogInline(q, btn) {
    btn.disabled = true;
    fetch('/qsl/not_in_log', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        call: q.call, band: q.band, mode: q.mode, qso_start: q.qso_start,
        dxcc_country: q.dxcc_country, qso_start_str: q.qso_start_str,
      }),
    }).then(r => r.json()).then(data => {
      btn.disabled = false;
      btn.classList.add('nil-marked');
      btn.textContent = 'Not in their log (Undo)';
      renderNotInLog(data.not_in_log || []);
    }).catch(() => { btn.disabled = false; });
  }

  function undoNotInLogInline(q, btn) {
    btn.disabled = true;
    fetch('/qsl/not_in_log/undo', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: notInLogKeyFor(q) }),
    }).then(r => r.json()).then(data => {
      btn.disabled = false;
      btn.classList.remove('nil-marked');
      btn.textContent = 'Not in their log';
      renderNotInLog(data.not_in_log || []);
    }).catch(() => { btn.disabled = false; });
  }

  function renderNotInLog(entries) {
    if (!entries || !entries.length) {
      notInLogContent.innerHTML = '<p class="not-in-log-empty">None flagged.</p>';
      return;
    }
    notInLogContent.innerHTML = entries.map(e => `
      <div class="not-in-log-row">
        <span class="nil-call">${e.call}</span>
        <span class="nil-meta">${e.dxcc_country || ''} -- ${e.band || ''} ${e.mode || ''} -- ${e.qso_start_str || ''}</span>
        <button data-key="${e.key}">Undo</button>
      </div>
    `).join('');
    notInLogContent.querySelectorAll('button[data-key]').forEach(btn => {
      btn.addEventListener('click', () => undoNotInLog(btn.dataset.key));
    });
  }

  function likelihoodBadge(likelihood) {
    const label = { high: 'High', medium: 'Medium', low: 'Low', unknown: 'Unknown' }[likelihood] || 'Unknown';
    return `<span class="badge badge-${likelihood}">${label}</span>`;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function renderExchangeLines(lines) {
    if (!lines.length) return '<em>No matching lines.</em>';
    // Verbatim ALL.TXT lines, unchanged apart from Tx/Rx coloring -- no
    // reconstructing/padding of fields.
    return lines.map(l =>
      `<div class="${l.rxtx === 'Tx' ? 'tx' : 'rx'}">${escapeHtml(l.raw)}</div>`
    ).join('');
  }

  function methodFormHtml(call, existing) {
    const m = existing || {};
    const options = METHODS.map(opt => `<option value="${opt}" ${m.method === opt ? 'selected' : ''}>${opt}</option>`).join('');
    return `
      <div class="method-form" data-call="${call}">
        <select class="m-method"><option value="">--</option>${options}</select>
        <input class="m-cost" type="text" placeholder="cost (e.g. $2 + SAE)" value="${m.cost ? m.cost.replace(/"/g, '&quot;') : ''}">
        <input class="m-notes" type="text" placeholder="notes" value="${m.notes ? m.notes.replace(/"/g, '&quot;') : ''}">
        <button class="m-save">Save</button>
        <span class="m-saved" style="display:none;" class="method-saved">Saved</span>
      </div>`;
  }

  function wireMethodForm(row, call) {
    const form = row.querySelector('.method-form');
    form.querySelector('.m-save').addEventListener('click', () => {
      const body = {
        call,
        method: form.querySelector('.m-method').value,
        cost: form.querySelector('.m-cost').value,
        notes: form.querySelector('.m-notes').value,
      };
      fetch('/qsl/methods', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }).then(r => r.json()).then(() => {
        const saved = form.querySelector('.m-saved');
        saved.style.display = 'inline';
        saved.textContent = 'Saved';
        setTimeout(() => { saved.style.display = 'none'; }, 1500);
        loadTodo();
      });
    });
  }

  const todoContent = root.getElementById('todo-content');
  const todoShowDone = root.getElementById('todo-show-done');

  function setMethodStatus(call, status) {
    fetch('/qsl/methods/status', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ call, status }),
    }).then(r => r.json()).then(() => loadTodo());
  }

  function renderTodo(methods) {
    const withMethod = (methods || []).filter(m => m.method);
    const showDone = todoShowDone.checked;
    const visible = withMethod.filter(m => showDone || m.status !== 'done');
    if (!visible.length) {
      todoContent.innerHTML = `<p class="todo-empty">${withMethod.length ? 'Nothing outstanding -- nice work.' : 'No QSL methods recorded yet -- set one from the "QSL method" column below.'}</p>`;
      return;
    }
    visible.sort((a, b) => (a.status === 'done') - (b.status === 'done'));
    const rows = visible.map(m => `
      <tr class="${m.status === 'done' ? 'todo-done-row' : ''}">
        <td>${m.call}</td>
        <td><span class="todo-method">${m.method}</span></td>
        <td>${m.cost || ''}</td>
        <td>${m.notes || ''}</td>
        <td><button data-call="${m.call}" data-status="${m.status === 'done' ? 'pending' : 'done'}">
          ${m.status === 'done' ? 'Reopen' : 'Mark Done'}
        </button></td>
      </tr>
    `).join('');
    todoContent.innerHTML = `
      <table class="todo-table">
        <thead><tr><th>Call</th><th>Method</th><th>Cost</th><th>Notes</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    todoContent.querySelectorAll('button[data-call]').forEach(btn => {
      btn.addEventListener('click', () => setMethodStatus(btn.dataset.call, btn.dataset.status));
    });
  }

  function loadTodo() {
    fetch('/qsl/data').then(r => r.json()).then(data => renderTodo(data.methods || [])).catch(() => {});
  }
  todoShowDone.addEventListener('change', loadTodo);

  function renderEntities(entities) {
    const countries = Object.keys(entities).sort();
    if (!countries.length) {
      content.innerHTML = '<p>No at-risk QSOs -- every DXCC entity you\'ve worked has at least one LoTW/eQSL/card confirmation. Nice.</p>';
      return;
    }
    content.innerHTML = '';
    countries.forEach(country => {
      const qsos = entities[country];
      const block = document.createElement('div');
      block.className = 'entity-block';
      block.innerHTML = `<h2>${country} <span style="font-weight:400;color:#888;">(${qsos.length} at-risk QSO${qsos.length > 1 ? 's' : ''})</span></h2>`;

      const table = document.createElement('table');
      table.className = 'qsl-table';
      table.innerHTML = `
        <thead><tr>
          <th>Call</th><th>My Call</th><th>Band</th><th>Mode</th><th>Date (UTC)</th>
          <th>Likelihood</th><th>Two-way?</th><th>RR73/73?</th><th class="col-snr">Avg SNR (Rx)</th><th>LoTW last active</th>
          <th>QSL method</th><th></th>
        </tr></thead>
        <tbody></tbody>`;
      const tbody = table.querySelector('tbody');

      qsos.forEach((q, idx) => {
        const rowId = 'ex-' + country.replace(/\W+/g, '') + '-' + idx;
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><div class="call-cell">${q.call} ${qrzLink(q.call)}</div></td>
          <td>${q.my_call}</td>
          <td>${q.band || ''}</td>
          <td>${q.mode || ''}</td>
          <td>${q.qso_start_str || ''}</td>
          <td>${likelihoodBadge(q.likelihood)}<div style="font-size:0.72rem;color:#888;max-width:16em;">${q.likelihood_reason}</div></td>
          <td>${q.two_way_confirmed ? 'Yes' : 'No'}</td>
          <td>${q.reached_rr73_or_73 ? 'Yes' : (q.saw_rrr_only ? 'RRR only' : 'No')}</td>
          <td class="col-snr">${q.avg_snr_rx ?? ''}</td>
          <td>${q.lotw_last_active || 'never'}</td>
          <td>${methodFormHtml(q.call, q.qsl_method)}</td>
          <td>
            <button class="exchange-toggle" data-target="${rowId}">${q.exchange_count} line${q.exchange_count === 1 ? '' : 's'} &#9660;</button>
            <br><button class="not-in-log-btn nil-mark">Not in their log</button>
          </td>
        `;
        tbody.appendChild(tr);
        wireMethodForm(tr, q.call);
        const nilBtn = tr.querySelector('.nil-mark');
        nilBtn.addEventListener('click', () => {
          if (nilBtn.classList.contains('nil-marked')) undoNotInLogInline(q, nilBtn);
          else markNotInLogInline(q, nilBtn);
        });

        const exRow = document.createElement('tr');
        const exCell = document.createElement('td');
        exCell.colSpan = 12;
        exCell.innerHTML = `<div class="exchange-panel" id="${rowId}">${renderExchangeLines(q.lines)}</div>`;
        exRow.appendChild(exCell);
        tbody.appendChild(exRow);
      });

      const scroller = document.createElement('div');
      scroller.className = 'qsl-table-scroll';
      scroller.appendChild(table);
      block.appendChild(scroller);
      content.appendChild(block);
    });

    content.querySelectorAll('.exchange-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        root.getElementById(btn.dataset.target).classList.toggle('open');
      });
    });
  }

  function load() {
    fetch('/qsl/data').then(r => r.json()).then(data => {
      if (data.error) { content.innerHTML = '<p>' + data.error + '</p>'; return; }
      renderCacheStatus(data.cache_status);
      renderLotwStatus(data.lotw_status);
      renderEntities(data.entities);
      renderTodo(data.methods || []);
      renderNotInLog(data.not_in_log || []);
    }).catch(err => { content.innerHTML = '<p>Failed to load: ' + err + '</p>'; });
  }

  reindexBtn.addEventListener('click', () => {
    cacheText.textContent = 'Re-scanning...';
    fetch('/qsl/reindex', { method: 'POST' }).then(r => r.json()).then(() => load());
  });

  lotwUpdateBtn.addEventListener('click', () => {
    lotwText.textContent = 'Downloading latest LoTW activity...';
    fetch('/qsl/lotw/update', { method: 'POST' }).then(r => r.json()).then(data => {
      if (!data.ok) { lotwText.textContent = 'LoTW update failed: ' + data.message; return; }
      load();
    });
  });

  load();
  const pollId = setInterval(load, 30000);

  return function unmount() {
    clearInterval(pollId);
  };
}

// -- Registration for the Dashboard applet loader. See
// static/live_monitor.js's near-identical comment for how this coexists
// with a real page navigation below.
window.DashboardApplets = window.DashboardApplets || {};
window.DashboardApplets['qsl_helper'] = {
  mount(root, ctx) { return mountQslHelper(root, ctx); },
};

// -- Auto-bootstrap for a real page navigation (the full /qsl page or the
// standalone /qsl/widget route) -- see static/live_monitor.js's
// near-identical note for why this guard is needed.
if (document.getElementById('content')) {
  mountQslHelper(document, null);
}

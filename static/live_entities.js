// live_entities.js -- DX Monitor's page logic, shared between the full page
// (templates/live_entities.html), its two standalone Dashboard widget
// routes (templates/live_entities_widget.html, /live/entities/widget/
// find|list), and -- as of the JS-applet migration, see
// /Users/darryl/.claude/plans/crystalline-bouncing-meteor.md -- the same
// two widgets mounted directly as shadow-DOM applets on the /dashboard page
// itself.
//
// mountLiveEntities(root, ctx, widgetMode) is the one implementation used
// by all of these -- see static/live_monitor.js's near-identical header
// comment for the full explanation of root/ctx/widgetMode and why. This
// file's history-replay handling was already ahead of live_monitor.js's
// pre-refactor version -- it always connected with ?no_history=1 and did
// its own explicit /live/dx_history REST catch-up (see the comment at that
// fetch call below), specifically so WSJT-X's own Erase doesn't wipe this
// screen -- so the shared/Dashboard live feed's own no_history=1 connection
// needed no behavior change here at all, only the transport swap (ctx.on/
// ctx.send instead of a raw WebSocket).
//
// New concern versus live_monitor.js's refactor: this file's Find/Scan
// feature runs a long-lived async loop (runScan(), spanning many seconds to
// hours with Loop) driven by chained setTimeout/await, not by a DOM event.
// Destroying an <iframe> document (the old per-widget-instance teardown)
// naturally aborts any JS still running inside it -- but removing a
// shadow-DOM tile's DOM does NOT stop a still-running async function
// whose closure references now-detached elements; it would keep silently
// re-tuning the radio and writing to `findStatus.textContent` on a
// disconnected element forever. unmount() below explicitly cancels an
// in-progress scan (equivalent to clicking Cancel) to preserve the safety
// guarantee removal used to provide for free.
function mountLiveEntities(root, ctx, widgetMode) {
  if (root.host) root.host.setAttribute('data-widget-mode', widgetMode || '');

  const dot = root.getElementById('dx-conn-dot');
  const connText = root.getElementById('dx-conn-text');
  const container = root.getElementById('dx-entities');
  const currentReadout = root.getElementById('dx-current');
  const filterRadios = root.querySelectorAll('input[name="dx-filter"]');
  const clearBtn = root.getElementById('dx-clear-btn');
  const unsubs = [];
  const intervalIds = [];

  // dxcc_name -> { entity_status, lastTime, lastSeenWallClock, calls: Map<"call@band", {call, snr, time_ms, call_status, band, dial_frequency_hz, delta_freq_hz, decodeTimes}> }
  // Keyed by call+band (not call alone) so the same callsign heard on two
  // different bands is tracked as two separate rows -- see computeGroupBoxes()
  // below for why that matters (per-band box splitting).
  const entities = new Map();

  // dial_frequency_hz -> [wall-clock decode times] -- every decode heard on
  // that exact dial frequency, regardless of whether its callsign resolved
  // to a known DXCC entity (unlike `entities` above). Feeds the per-band
  // frequency-activity grid below the Find box.
  const freqActivity = new Map();

  // Same band table/convention as the Remote tab's band-button highlighting,
  // used here purely to know what "current band" means for the filter modes
  // -- the server's own freq_to_band() (live_monitor.py) already stamps a
  // per-decode "band" field, but Status broadcasts don't carry one, so the
  // current band has to be derived client-side from dial_frequency_hz.
  const BAND_TABLE = [
    [1.8, 2.0, '160M'], [3.5, 4.0, '80M'], [5.3, 5.4, '60M'], [7.0, 7.3, '40M'],
    [10.1, 10.15, '30M'], [14.0, 14.35, '20M'], [18.068, 18.168, '17M'],
    [21.0, 21.45, '15M'], [24.89, 24.99, '12M'], [28.0, 29.7, '10M'],
    [50.0, 54.0, '6M'], [70.0, 70.5, '4M'], [144.0, 148.0, '2M'],
  ];
  function freqToBand(hz) {
    if (!hz) return null;
    const mhz = hz / 1e6;
    const match = BAND_TABLE.find(([lo, hi]) => mhz >= lo && mhz <= hi);
    return match ? match[2] : null;
  }

  let currentDialHz = null;
  let currentBand = null;
  // Fed by WSJT-X's own Status broadcasts (same field the Remote tab uses
  // for its yellow "transmitting" highlight) -- used by the Find scan loop
  // below to auto-cancel if the radio starts transmitting for any reason
  // *other* than the scan's own deliberate Tune burst.
  let currentlyTransmitting = false;
  function applyStatus(ev) {
    if (ev.dial_frequency_hz) {
      currentDialHz = ev.dial_frequency_hz;
      currentBand = freqToBand(currentDialHz);
    }
    if ('transmitting' in ev) currentlyTransmitting = !!ev.transmitting;
    currentReadout.textContent = currentBand
      ? `Current: ${currentBand} ${(currentDialHz / 1e6).toFixed(6)}` : '';
  }

  let filterMode = localStorage.getItem('dx_filter_mode') || 'all';
  filterRadios.forEach(r => {
    r.checked = (r.value === filterMode);
    r.addEventListener('change', () => {
      if (r.checked) { filterMode = r.value; localStorage.setItem('dx_filter_mode', filterMode); renderAll(); }
    });
  });

  // Band/band+frequency filtering is per-station (each call carries its own
  // last-heard band/frequency), not per-entity -- a DXCC entity can have
  // stations heard on different bands over its 6h lifetime.
  function passesFilter(info) {
    if (filterMode === 'all') return true;
    if (!currentBand || info.band !== currentBand) return false;
    if (filterMode === 'band') return true;
    return info.dial_frequency_hz != null && currentDialHz != null && info.dial_frequency_hz === currentDialHz;
  }

  // "Clear" only removes what the current filter shows -- e.g. in "Current
  // band" mode it clears just that band's stations, leaving others intact.
  // Deliberately NOT wired to WSJT-X's own Erase/'clear' broadcast -- this
  // screen is meant to hold a longer history than the live decode window,
  // so an Erase over there shouldn't wipe it here.
  function clearByFilter() {
    if (filterMode === 'all') {
      entities.clear();
      renderAll();
      return;
    }
    const emptyEntities = [];
    for (const [name, group] of entities) {
      const toDelete = [];
      for (const [call, info] of group.calls) {
        if (passesFilter(info)) toDelete.push(call);
      }
      toDelete.forEach(call => group.calls.delete(call));
      if (group.calls.size === 0) emptyEntities.push(name);
    }
    emptyEntities.forEach(name => entities.delete(name));
    renderAll();
  }
  clearBtn.addEventListener('click', clearByFilter);

  // Six equal 15-minute activity-box windows (per callsign, based on decode
  // wall-clock times -- how often heard, not how often worked), covering
  // the most recent 90 minutes. All six are the same width, so this is just
  // a raw count per box -- no normalization needed (that was only required
  // for the earlier variable-width design).
  const ACTIVITY_BUCKET_MS = 15 * 60 * 1000;
  const ACTIVITY_BUCKET_COUNT = 6;

  // Entity/decode-history timeout deliberately matches the activity boxes'
  // own total span, not an independent number -- once a station falls
  // outside every box (all six would show empty), there's nothing left to
  // show for it, so it should disappear rather than linger. WSJT-X's own
  // time_ms field is only ms-since-midnight-UTC (see fmtTime), not a real
  // timestamp, so it can't tell you how long ago something actually was
  // once you're near a day boundary -- lastSeenWallClock is a real
  // Date.now() captured whenever a live decode updates a group, used only
  // for this expiry check.
  const TIMEOUT_MS = ACTIVITY_BUCKET_MS * ACTIVITY_BUCKET_COUNT;

  function computeActivityBoxes(decodeTimes, now) {
    const counts = new Array(ACTIVITY_BUCKET_COUNT).fill(0);
    decodeTimes.forEach(t => {
      const age = now - t;
      const i = Math.floor(age / ACTIVITY_BUCKET_MS);
      if (i >= 0 && i < ACTIVITY_BUCKET_COUNT) counts[i]++;
    });
    return counts.map((count, i) => ({
      label: `${i * 15}-${(i + 1) * 15}m`, count,
    }));
  }

  // Color ramp for the raw count in a box -- grey (none heard) up through
  // blue/amber/red. MAX_COUNT is where the ramp saturates (tune against
  // real observed activity levels).
  const ACTIVITY_MAX_COUNT = 8;
  function activityColor(count) {
    if (count <= 0) return '#e2e2e2';
    const t = Math.max(0, Math.min(1, count / ACTIVITY_MAX_COUNT));
    const stops = [
      [0, [191, 219, 254]], [0.4, [59, 130, 246]], [0.7, [245, 158, 11]], [1, [211, 47, 47]],
    ];
    for (let i = 0; i < stops.length - 1; i++) {
      const [t0, c0] = stops[i], [t1, c1] = stops[i + 1];
      if (t <= t1 || i === stops.length - 2) {
        const f = Math.max(0, Math.min(1, (t - t0) / (t1 - t0 || 1)));
        const c = c0.map((v, k) => Math.round(v + (c1[k] - v) * f));
        return `rgb(${c[0]},${c[1]},${c[2]})`;
      }
    }
    return 'rgb(211,47,47)';
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
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

  // "Time since last contact" for an entity's header row -- real wall-clock
  // minutes (lastSeenWallClock, not WSJT-X's ms-since-midnight time_ms), so
  // it stays correct across a day boundary and across a page reload replay.
  function fmtAgo(ageMs) {
    const mins = Math.floor(ageMs / 60000);
    return mins < 2 ? 'now' : `${mins}m`;
  }

  function tickUtcClock() {
    const el = root.getElementById('dx-utc-clock');
    if (el) el.textContent = fmtTime(Date.now() % 86400000) + ' UTC';
  }
  tickUtcClock();
  intervalIds.push(setInterval(tickUtcClock, 1000));

  function handleDecode(ev) {
    // Frequency-activity tracking happens for every decode with a known
    // dial frequency, even ones the entity grouping below skips (calls that
    // didn't resolve to a DXCC entity still count as "this frequency is
    // active").
    if (ev.dial_frequency_hz != null) {
      const freqWallClock = ev.received_epoch_ms ?? Date.now();
      const freqTimes = freqActivity.get(ev.dial_frequency_hz) || [];
      freqTimes.push(freqWallClock);
      const freqNow = Date.now();
      while (freqTimes.length && freqNow - freqTimes[0] > TIMEOUT_MS) freqTimes.shift();
      freqActivity.set(ev.dial_frequency_hz, freqTimes);
    }
    if (!ev.call || !ev.dxcc_name) return; // unresolvable/hashed calls -- nothing to group by
    let group = entities.get(ev.dxcc_name);
    if (!group) {
      group = { calls: new Map() };
      entities.set(ev.dxcc_name, group);
    }
    group.entity_status = ev.entity_status;
    group.lastTime = ev.time_ms;
    // Use the server's real wall-clock stamp when present (both live decodes
    // and /live/history replay carry it) instead of Date.now(), so a
    // replayed historical decode is aged correctly instead of always looking
    // like it just happened -- that was the actual cause of entities/boxes
    // losing their history on a page reload (see
    // project_live_history_buffer_size). Falls back to Date.now() only for
    // events from before this field existed.
    const wallClock = ev.received_epoch_ms ?? Date.now();
    group.lastSeenWallClock = Math.max(group.lastSeenWallClock ?? 0, wallClock);
    // Keyed by call+band, not call alone -- the same callsign heard on two
    // different bands is two distinct rows (this is exactly what makes the
    // per-band box split below possible; keying by call alone would have
    // the second band's decode silently clobber the first's).
    const callKey = `${ev.call}@${ev.band || ''}`;
    const prevInfo = group.calls.get(callKey);
    const decodeTimes = (prevInfo && prevInfo.decodeTimes) || [];
    decodeTimes.push(wallClock);
    // Prune this call's own history to the same 6h window as the entity
    // timeout, so it doesn't grow unbounded for a call heard continuously.
    const now = Date.now();
    while (decodeTimes.length && now - decodeTimes[0] > TIMEOUT_MS) decodeTimes.shift();
    group.calls.set(callKey, {
      call: ev.call, snr: ev.snr, time_ms: ev.time_ms, call_status: ev.call_status, decodeTimes,
      band: ev.band, dial_frequency_hz: ev.dial_frequency_hz,
      // Full decode event, kept so a double-click can tune+reply exactly as
      // Remote/Live Monitor's double-click-to-call does -- see tuneAndCall().
      rawEvent: ev,
    });
    // No size cap here any more -- capping to "3 most recent" now happens
    // per rendered box (renderAll() below), since what counts as "one box"
    // changed (per-band split vs a combined multi-band box). Stale
    // call+band entries are still reclaimed, just in pruneExpired() instead
    // of here, once their own decode history ages out.
  }

  function pruneExpired() {
    const now = Date.now();
    for (const [name, group] of entities) {
      if (now - (group.lastSeenWallClock ?? now) > TIMEOUT_MS) { entities.delete(name); continue; }
      for (const [callKey, info] of group.calls) {
        const dt = info.decodeTimes || [];
        while (dt.length && now - dt[0] > TIMEOUT_MS) dt.shift();
        if (dt.length === 0) group.calls.delete(callKey);
      }
    }
  }

  function freqLabel(info, includeBand) {
    if (!info.band) return '';
    // Just the dial frequency the radio was tuned to -- not each decode's
    // own audio-passband offset added in (that gave a different, noisier
    // number per station, e.g. 21.075340, instead of the one real dial
    // setting, e.g. 21.074, that they were all actually heard on).
    const mhz = info.dial_frequency_hz != null ? (info.dial_frequency_hz / 1e6).toFixed(3) : '';
    if (!includeBand) return mhz;
    return mhz ? `${info.band} ${mhz}` : info.band;
  }

  const MAX_ROWS_PER_BOX = 3;

  // Builds one .dx-group box's HTML from exactly the rows given -- callers
  // decide how many and which (an orange/red band box caps at 3 most
  // recent; a green box's row count follows its own more involved rule,
  // see computeGroupBoxes below, and must NOT be silently re-capped here).
  // `heading` is either just the DXCC name, or "Name - Band"; `showBandPerRow`
  // controls whether each row repeats the band (only useful when a single
  // box spans more than one band).
  function renderBox(heading, statusScope, callEntries, lastSeenWallClock, now, showBandPerRow) {
    const rows = callEntries.slice().sort((a, b) => (b[1].time_ms ?? 0) - (a[1].time_ms ?? 0));
    const callRows = rows.map(([callKey, info]) => {
      const boxes = computeActivityBoxes(info.decodeTimes || [], now).map(b => `
        <span class="dx-box" style="background:${activityColor(b.count)}" title="${b.label}: ${b.count} decode${b.count === 1 ? '' : 's'}"></span>
      `).join('');
      return `
      <div class="dx-call-row" data-entity="${escapeHtml(info.entityName)}" data-call="${escapeHtml(callKey)}" title="Double-click to tune + call ${escapeHtml(info.call)}">
        <span class="dx-call ${statusClass(info.call_status && info.call_status.band)}">${escapeHtml(info.call)}</span>
        <span class="dx-snr">${info.snr ?? ''} dB</span>
        <span class="dx-time">${fmtTime(info.time_ms)}</span>
        <span class="dx-freq">${freqLabel(info, showBandPerRow)}</span>
        <span class="dx-activity">${boxes}</span>
      </div>
    `;
    }).join('');
    const agoMs = now - (lastSeenWallClock ?? now);
    return `
      <div class="dx-group">
        <div class="dx-header">
          <span class="${statusClass(statusScope)}">${escapeHtml(heading)}</span>
          <span class="dx-last-heard" title="Time since last heard">${fmtAgo(agoMs)}</span>
        </div>
        ${callRows}
      </div>
    `;
  }

  // Status is genuinely per-band, not per-DXCC -- confirmed on 30M and not
  // yet worked on 15M can both be true for the same entity at once (the
  // server already computes it this way: entity_status.band is scoped to
  // *this decode's own band*, see live_monitor.py's _handle_decode()).
  // Takes it from a band-group's most recent call -- every call in the
  // group shares the same band, so they should all agree.
  function bandStatus(bandCalls) {
    const ev = bandCalls[0][1].rawEvent;
    return (ev && ev.entity_status && ev.entity_status.band) || 'none';
  }

  const MAX_GREEN_BANDS_BEFORE_ONE_PER_BAND = 3;

  // One DXCC can become several boxes, split purely by each band's own
  // status:
  //  - Every not-yet-confirmed (orange/red) band gets its own box, up to 3
  //    of its most recently-heard callsigns, heading "Name - Band" with
  //    the now-redundant band dropped from each row.
  //  - All confirmed (green) bands combine into a *single* shared green
  //    box instead (there's no separate "opportunity" left per green band
  //    the way there is for orange/red) -- every confirmed band gets at
  //    least one representative row so it stays visible, padded with
  //    whatever's next most recent (possibly a second/third station on the
  //    same band) up to 3 rows total if that many exist. Once more than 3
  //    bands are confirmed, padding stops making sense (3 rows couldn't
  //    represent them all anyway) and it switches to exactly one row per
  //    band instead, however many bands that is.
  // Returns this DXCC's boxes as a flat array of { isGreen, lastTime, html }
  // -- NOT bundled together as one per-DXCC unit. A DXCC that's confirmed
  // on one band and not on another produces two independent boxes here,
  // deliberately, so renderAll() below can sink the confirmed one to the
  // bottom with every other DXCC's confirmed boxes while the not-yet-
  // confirmed one stays up top with the other open opportunities -- they
  // don't stay glued together just because they share a DXCC name.
  function computeGroupBoxes(name, group, now) {
    const calls = Array.from(group.calls.entries())
      .filter(([, info]) => passesFilter(info))
      .map(([callKey, info]) => [callKey, { ...info, entityName: name }]);
    if (calls.length === 0) return [];

    const byBand = new Map();
    for (const entry of calls) {
      const band = entry[1].band || '';
      if (!byBand.has(band)) byBand.set(band, []);
      byBand.get(band).push(entry);
    }
    for (const bandCalls of byBand.values()) {
      bandCalls.sort((a, b) => (b[1].time_ms ?? 0) - (a[1].time_ms ?? 0));
    }

    const greenBands = [];
    const boxes = []; // { isGreen, lastTime, html }
    for (const [band, bandCalls] of byBand.entries()) {
      const status = bandStatus(bandCalls);
      if (status === 'confirmed') {
        greenBands.push([band, bandCalls]);
        continue;
      }
      boxes.push({
        isGreen: false,
        lastTime: bandCalls[0][1].time_ms ?? 0,
        html: renderBox(`${name} - ${band}`, status, bandCalls.slice(0, MAX_ROWS_PER_BOX), group.lastSeenWallClock, now, false),
      });
    }

    if (greenBands.length > 0) {
      let greenRows;
      if (greenBands.length > MAX_GREEN_BANDS_BEFORE_ONE_PER_BAND) {
        greenRows = greenBands.map(([, bandCalls]) => bandCalls[0]);
      } else {
        const mustInclude = greenBands.map(([, bandCalls]) => bandCalls[0]);
        const included = new Set(mustInclude.map(([callKey]) => callKey));
        const rest = greenBands.flatMap(([, bandCalls]) => bandCalls)
          .filter(([callKey]) => !included.has(callKey))
          .sort((a, b) => (b[1].time_ms ?? 0) - (a[1].time_ms ?? 0));
        greenRows = mustInclude.concat(rest).slice(0, MAX_ROWS_PER_BOX);
      }
      greenRows.sort((a, b) => (b[1].time_ms ?? 0) - (a[1].time_ms ?? 0));
      const singleBand = greenBands.length === 1 ? greenBands[0][0] : null;
      boxes.push({
        isGreen: true,
        lastTime: Math.max(...greenRows.map(([, info]) => info.time_ms ?? 0)),
        html: renderBox(
          singleBand ? `${name} - ${singleBand}` : name,
          'confirmed', greenRows, group.lastSeenWallClock, now, !singleBand,
        ),
      });
    }

    return boxes;
  }

  function renderAll() {
    renderFreqGrid();
    pruneExpired();
    if (entities.size === 0) {
      container.innerHTML = '<p class="dx-empty">No decodes yet -- waiting for WSJT-X.</p>';
      return;
    }
    const now = Date.now();
    // Flat list of every box across every DXCC -- deliberately NOT grouped
    // back by DXCC before sorting. A confirmed (green) box sinks to the
    // bottom with every other DXCC's confirmed boxes, regardless of
    // whether *this* DXCC also still has a not-yet-confirmed band open on
    // another box; that other box stays up top on its own. Within each
    // tier, most-recently-heard stays on top.
    const allBoxes = [];
    for (const [name, group] of entities) allBoxes.push(...computeGroupBoxes(name, group, now));
    allBoxes.sort((a, b) => {
      if (a.isGreen !== b.isGreen) return a.isGreen ? 1 : -1;
      return b.lastTime - a.lastTime;
    });
    const groupsHtml = allBoxes.map(b => b.html);
    container.innerHTML = groupsHtml.length
      ? groupsHtml.join('')
      : `<p class="dx-empty">Nothing matches this filter${currentBand ? '' : ' (waiting for WSJT-X status to know the current band)'}.</p>`;
  }

  // -- Double-click a callsign row: tune the radio to where it was last
  // heard (if not already there), then call it exactly as double-clicking
  // that decode inside WSJT-X itself would (same /live/ws 'reply' action
  // Remote/Live Monitor use -- see live_monitor.py's handle_reply_action).
  const callStatus = root.getElementById('dx-call-status');

  function sendReply(ev) {
    ctx.send({ action: 'reply', event: ev });
    callStatus.textContent = `Calling ${ev.call || ''}...`;
    // WSJT-X only auto-arms Enable Tx itself for a *real* double-click reply
    // to a CQ decode -- non-CQ calls go through Configure instead (see
    // handle_reply_action()'s docstring in live_monitor.py: Reply is
    // hard-filtered by WSJT-X to CQ/QRZ messages only), which sets DX Call/
    // Grid but does NOT arm Tx, so it just sits there never actually
    // calling until the operator remembers to click Enable Tx themselves
    // (a real WSJT-X quirk, not something Configure is supposed to fix).
    // arm_tx_checkbox() is a no-op if Enable Tx is already on, so this is
    // safe to send unconditionally.
    if (!ev.is_cq) {
      postJson('/remote/gui/checkbox', { name: 'Enable Tx', on: true }).catch(() => {});
    }
  }

  // Reads the rig's *actual* current frequency directly from rigctld, not
  // the cached currentDialHz (fed only by WSJT-X's own Status broadcasts,
  // which can be stale or simply behind if the dial was moved by anything
  // other than WSJT-X -- confirmed live as a real way for tuneAndCall() to
  // wrongly decide "already there" and skip tuning entirely).
  async function fetchActualDialHz() {
    try {
      const status = await fetch('/radio/status').then(r => r.json());
      return typeof status.frequency_hz === 'number' ? status.frequency_hz : null;
    } catch (e) {
      return null;
    }
  }

  // Polls rigctld until it actually reports the target frequency (rigctld
  // sets it exactly, so no rounding tolerance needed) or timeoutMs elapses
  // -- replaces an earlier flat 1500ms guess-wait that never confirmed the
  // rig had actually gotten there before calling.
  async function waitForActualDialHz(targetHz, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await fetchActualDialHz() === targetHz) return true;
      await new Promise(r => setTimeout(r, 300));
    }
    return false;
  }

  // Guards against two overlapping tuneAndCall() calls (e.g. a fast second
  // double-click, on the same row or a different one, before the first
  // one's tune has even finished) racing each other's /radio/frequency
  // POSTs -- confirmed live this could previously leave the radio on
  // whichever tune request happened to land last, independent of which
  // callsign's reply was actually sent.
  let tuneAndCallBusy = false;

  async function tuneAndCall(ev) {
    if (tuneAndCallBusy) {
      callStatus.textContent = `Still tuning/calling -- try double-clicking ${ev.call || 'that station'} again in a moment.`;
      return;
    }
    tuneAndCallBusy = true;
    try {
      const targetHz = ev.dial_frequency_hz;
      if (targetHz != null) {
        const actualHz = await fetchActualDialHz();
        if (actualHz !== targetHz) {
          const freqLabel = (targetHz / 1e6).toFixed(6);
          callStatus.textContent = `Tuning to ${freqLabel}...`;
          let d;
          try {
            d = await postJson('/radio/frequency', { frequency_hz: targetHz });
          } catch (e) {
            callStatus.textContent = `Tune failed: ${e.message || e} -- not calling.`;
            return;
          }
          if (!d.ok) {
            callStatus.textContent = `Tune failed: ${d.error || 'rig rejected the frequency'} -- not calling.`;
            return;
          }
          callStatus.textContent = `Tuning to ${freqLabel}... confirming`;
          const confirmed = await waitForActualDialHz(targetHz, 4000);
          if (!confirmed) {
            // Best-effort: still call rather than getting permanently stuck
            // if e.g. rigctld's own status poll is just slow, but say so
            // plainly instead of silently pretending the tune was verified.
            callStatus.textContent = `Rig hasn't confirmed ${freqLabel} yet -- calling anyway.`;
          }
        }
      }
      sendReply(ev);
    } finally {
      tuneAndCallBusy = false;
    }
  }

  // Regression (live 2026-08-16): double-clicking a station tuned+called
  // correctly, but the radio was left on a *different* band than the row
  // said -- a Find/Scan was mid-cycle in a *separate* Dashboard tile ("DX
  // Monitor: Find" is its own widget, independent from the entity-list
  // widget the double-click happened in). Same-widget cancellation
  // (cancelScan()/activeScanPromise below) only ever touches *this*
  // mounted instance's own JS state -- it has no way to see, let alone
  // cancel, a scan loop running in a different tile's (or a different
  // browser tab's) separate closure, so the scan's own next tune raced
  // tuneAndCall()'s and won. Fixed by coordinating over the shared /live/ws
  // feed instead of local variables: broadcast a cancel request that every
  // connected instance receives (see ctx.on('scan_cancel_requested', ...)
  // below), and wait for whichever one is actually scanning (if any) to
  // ack once its loop has genuinely unwound.
  let scanCancelledAckWaiters = [];
  function waitForScanCancelledAck(timeoutMs) {
    return new Promise(resolve => {
      let done = false;
      const finish = () => { if (!done) { done = true; resolve(); } };
      scanCancelledAckWaiters.push(finish);
      setTimeout(finish, timeoutMs);
    });
  }

  container.addEventListener('dblclick', async (e) => {
    const row = e.target.closest('.dx-call-row');
    if (!row) return;
    const group = entities.get(row.dataset.entity);
    const info = group && group.calls.get(row.dataset.call);
    if (!info || !info.rawEvent) return;
    // A running Find/Scan is actively re-tuning the radio -- calling a
    // station only makes sense once the scan is genuinely out of the way,
    // not just once it's been *asked* to stop.
    if (!findCancelBtn.disabled) {
      // Scan is running in *this* instance -- cancel directly, no network
      // round trip needed. cancelScan() only sets flags and fires
      // best-effort cleanup; actually wait for its still-running loop
      // iteration to finish unwinding so its own in-flight /radio/frequency
      // call can't land after (and override) tuneAndCall()'s.
      cancelScan();
      if (activeScanPromise) await activeScanPromise;
    } else {
      // No scan running *here* -- but one might be running in a different
      // tile/tab. /live/find_config's "scanning" flag is the server-
      // persisted signal every instance already keeps in sync (used for
      // the resume-on-reload feature), so check it before paying for the
      // broadcast+wait round trip on the common case where nothing's
      // scanning anywhere.
      let scanningElsewhere = false;
      try {
        const cfg = await fetch('/live/find_config').then(r => r.json());
        scanningElsewhere = !!cfg.scanning;
      } catch (e) { /* best-effort -- fall through and tune anyway */ }
      if (scanningElsewhere) {
        const ackPromise = waitForScanCancelledAck(8000);
        ctx.send({ action: 'request_scan_cancel' });
        await ackPromise;
      }
    }
    tuneAndCall(info.rawEvent);
  });

  fetch('/live/config').then(r => r.json()).then(data => {
    if (data.wsjtx_status && Object.keys(data.wsjtx_status).length) { applyStatus(data.wsjtx_status); renderAll(); }
  }).catch(() => {});

  unsubs.push(ctx.onStatus(connected => {
    dot.className = connected ? 'up' : 'down';
    connText.textContent = connected ? 'connected' : 'disconnected -- retrying...';
  }));
  unsubs.push(ctx.on('decode', ev => { handleDecode(ev); renderAll(); }));
  unsubs.push(ctx.on('status', ev => { applyStatus(ev); renderAll(); }));
  // See the dblclick handler's own comment above for why this exists:
  // Find/Scan and the double-click that wants it out of the way can be in
  // two entirely separate mounted instances (different Dashboard tiles, or
  // different browser tabs/devices), so cancellation has to travel over
  // the shared feed rather than through local variables alone. Every
  // instance listens; only whichever one actually has a scan running does
  // anything in response.
  unsubs.push(ctx.on('scan_cancel_requested', async () => {
    if (!findCancelBtn.disabled) {
      cancelScan();
      if (activeScanPromise) await activeScanPromise;
      ctx.send({ action: 'scan_cancelled' });
    }
  }));
  unsubs.push(ctx.on('scan_cancelled_ack', () => {
    const waiters = scanCancelledAckWaiters;
    scanCancelledAckWaiters = [];
    waiters.forEach(fn => fn());
  }));
  // A station's orange/green colour used to be frozen to whatever the
  // logbook said the moment it was decoded -- a QSL received/logged later
  // never updated it, since nothing recomputed an *existing* entry, only
  // fresh decodes ever got looked up (confirmed live 2026-08-19: a real
  // LoTW confirmation stayed invisible here until the station happened to
  // be heard again). live_monitor.py now polls the logbook file itself and
  // broadcasts this event whenever it changes -- patch every affected
  // call+band's status in place (including relocating it to a different
  // DXCC group, on the rare chance its resolution itself changed) rather
  // than waiting for a fresh decode.
  unsubs.push(ctx.on('status_refresh', ev => {
    let changed = false;
    (ev.updates || []).forEach(u => {
      const oldGroup = entities.get(u.old_dxcc_name);
      if (!oldGroup) return;
      const key = `${u.call}@${u.band || ''}`;
      const info = oldGroup.calls.get(key);
      if (!info) return; // not currently tracked here (e.g. already aged out) -- nothing to patch
      info.call_status = u.call_status;
      info.rawEvent = { ...info.rawEvent, ...u };
      if (u.dxcc_name !== u.old_dxcc_name) {
        oldGroup.calls.delete(key);
        let newGroup = entities.get(u.dxcc_name);
        if (!newGroup) {
          newGroup = { calls: new Map(), lastSeenWallClock: oldGroup.lastSeenWallClock, lastTime: oldGroup.lastTime };
          entities.set(u.dxcc_name, newGroup);
        }
        newGroup.calls.set(key, info);
        newGroup.lastSeenWallClock = Math.max(newGroup.lastSeenWallClock ?? 0, oldGroup.lastSeenWallClock ?? 0);
        newGroup.lastTime = Math.max(newGroup.lastTime ?? 0, info.time_ms ?? 0);
      }
      changed = true;
    });
    if (changed) renderAll();
  }));
  // Deliberately NOT listening for 'clear' (WSJT-X's own Erase) here -- see
  // clearByFilter() above for why. Only the page's own Clear button removes
  // anything from this screen.

  // /live/dx_history (not /live/history) -- this page's own Erase-
  // independent replay buffer, see live_monitor.py's LiveMonitor.dx_history.
  // ctx's feed always connects with no_history=1 (true for both the shared
  // Dashboard connection, which can't replay per-widget on demand, and the
  // standalone adapter below) -- this fetch is what actually populates
  // history, same as it always was; only the live-event transport changed.
  fetch('/live/dx_history').then(r => r.json()).then(events => {
    events.forEach(ev => { if (ev.kind === 'decode') handleDecode(ev); });
    renderAll();
  }).catch(() => {});

  // Re-render periodically even with no new decodes, so an entity actually
  // disappears close to the TIMEOUT_MS mark (rather than lingering until
  // whenever the next unrelated decode happens to trigger a re-render) and
  // so the "time since last heard" header label keeps ticking forward.
  intervalIds.push(setInterval(renderAll, 30 * 1000));

  // -- Find: scan a chosen set of frequency presets (Frequencies tab,
  // flagged "Find"), one at a time. Tunes the rig directly via rigctld
  // (/radio/frequency) instead of clicking WSJT-X's own band button, per
  // the user's own "move away from WSJT-X band buttons" direction -- only
  // the optional Tune burst still goes through WSJT-X's own GUI bridge
  // (wsjtx_gui_bridge.py via /remote/gui/checkbox), since Tune itself has
  // no rigctld equivalent. Currently embedded here; may move to its own
  // page later, per the user's own note when this was requested.
  const findBandsContainer = root.getElementById('dx-find-bands');
  const findTuneBox = root.getElementById('find-tune-enabled');
  const findLoopBox = root.getElementById('find-loop');
  const findScanBtn = root.getElementById('find-scan-btn');
  const findCancelBtn = root.getElementById('find-cancel-btn');
  const findStatus = root.getElementById('find-status');

  function postJson(url, body) {
    return fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
    }).then(r => r.json());
  }

  // Presets flagged "find" -- fetched once on load alongside the saved
  // selection; edit the Frequencies tab and reload this page to pick up
  // changes. Kept around so the scan loop can look up freq_hz by id.
  let findPresets = [];

  // Every write to /live/find_config -- preset/tune/loop changes AND the
  // scanning flag below -- funnels through this one chain so concurrent
  // saves can never complete out of order and silently clobber each other
  // (e.g. a rapid check-then-uncheck firing two overlapping unawaited POSTs
  // with no guarantee the second actually lands after the first).
  let findConfigSaveChain = Promise.resolve();
  function postFindConfig(body) {
    findConfigSaveChain = findConfigSaveChain.then(() => postJson('/live/find_config', body).catch(() => {}));
    return findConfigSaveChain;
  }

  function saveFindConfig() {
    return postFindConfig({
      preset_ids: Array.from(findBandsContainer.querySelectorAll('.find-band'))
        .filter(cb => cb.checked).map(cb => cb.value),
      tune_enabled: findTuneBox.checked,
      loop: findLoopBox.checked,
    });
  }

  // Persisted so a reloaded page (the common real trigger: macOS/browser
  // discarding a backgrounded tab, not a crash -- see
  // project_dx_monitor_find_scan_reload_resume) knows a scan was actually
  // in progress last time anyone saved this file, and can resume it instead
  // of just silently sitting idle forever with nothing telling the user
  // their overnight Loop scan died hours ago.
  function setScanningFlag(scanning) {
    return postFindConfig({ scanning });
  }

  function renderFindPresets(savedIds) {
    findBandsContainer.innerHTML = '';
    if (findPresets.length === 0) {
      findBandsContainer.textContent = 'No presets flagged "Find" -- add some on the Frequencies tab.';
      return;
    }
    findPresets.forEach(p => {
      const label = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'find-band';
      cb.value = String(p.id);
      cb.checked = savedIds.has(String(p.id));
      cb.addEventListener('change', () => { saveFindConfig(); renderFreqGrid(); });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(` ${p.name} (${(p.freq_hz / 1e6).toFixed(6)})`));
      findBandsContainer.appendChild(label);
    });
  }

  findTuneBox.addEventListener('change', saveFindConfig);
  findLoopBox.addEventListener('change', saveFindConfig);

  // One column per band (in BAND_TABLE frequency order, only bands that
  // actually have a Find-flagged preset), one row per preset on that band,
  // boxes styled like the per-callsign activity boxes -- but WHITE instead
  // of grey when that specific preset's checkbox isn't currently checked,
  // so it's visually obvious which frequencies are actually part of the
  // active scan selection vs. just configured-but-not-selected right now.
  function renderFreqGrid() {
    const grid = root.getElementById('dx-freq-grid');
    if (!grid) return;
    if (findPresets.length === 0) { grid.innerHTML = ''; return; }
    const checkedIds = new Set(Array.from(findBandsContainer.querySelectorAll('.find-band'))
      .filter(cb => cb.checked).map(cb => cb.value));
    const now = Date.now();
    const byBand = new Map();
    findPresets.forEach(p => {
      const band = freqToBand(p.freq_hz);
      if (!band) return;
      if (!byBand.has(band)) byBand.set(band, []);
      byBand.get(band).push(p);
    });
    const bandOrder = BAND_TABLE.map(b => b[2]).filter(b => byBand.has(b));
    grid.innerHTML = bandOrder.map(band => {
      const presets = byBand.get(band).slice().sort((a, b) => a.freq_hz - b.freq_hz);
      const rows = presets.map(p => {
        const isSelected = checkedIds.has(String(p.id));
        const times = freqActivity.get(p.freq_hz) || [];
        const boxes = computeActivityBoxes(times, now).map(b => {
          const bg = isSelected ? activityColor(b.count) : '#ffffff';
          const note = isSelected ? '' : ' -- not currently selected for scanning';
          return `<span class="dx-box" style="background:${bg}" title="${escapeHtml(p.name)} ${(p.freq_hz / 1e6).toFixed(6)} -- ${b.label}: ${b.count} decode${b.count === 1 ? '' : 's'}${note}"></span>`;
        }).join('');
        return `
          <div class="freq-row">
            <span>${(p.freq_hz / 1e6).toFixed(3)}</span>
            <span class="dx-activity">${boxes}</span>
          </div>
        `;
      }).join('');
      return `
        <div class="freq-band-col">
          <div class="freq-band-header">${escapeHtml(band)}</div>
          ${rows}
        </div>
      `;
    }).join('');
  }

  Promise.all([
    fetch('/frequencies/presets').then(r => r.json()),
    fetch('/live/find_config').then(r => r.json()),
  ]).then(([presetsData, cfg]) => {
    findPresets = (presetsData.presets || []).filter(p => p.find);
    findTuneBox.checked = !!cfg.tune_enabled;
    findLoopBox.checked = !!cfg.loop;
    renderFindPresets(new Set((cfg.preset_ids || []).map(String)));
    renderFreqGrid();
    // cfg.scanning is only ever left true if a scan was genuinely still
    // running the last time this file was saved -- both normal completion
    // and Cancel clear it (see runScan()/cancelScan()). In practice this
    // means the page reloaded (commonly the browser discarding a
    // backgrounded tab, not a crash) while a scan -- often an unattended
    // overnight Loop -- was mid-flight, so pick it back up automatically
    // rather than leaving it silently dead until someone happens to notice.
    if (cfg.scanning) {
      findStatus.textContent = 'Resuming scan after reload...';
      startScan();
    }
  }).catch(() => {});

  // Tracks the in-flight runScan() call (if any) so other code -- notably
  // the double-click-to-call handler below -- can actually *wait* for a
  // cancelled scan to finish unwinding instead of racing it. cancelScan()
  // only sets flags/fires best-effort cleanup calls; the scan loop itself
  // can still have an /radio/frequency or Tune POST in flight for up to a
  // few hundred ms after cancelScan() returns, which used to be able to
  // land *after* (and silently override) a double-click's own tune --
  // confirmed live as a real race, not theoretical.
  let activeScanPromise = null;
  function startScan() {
    activeScanPromise = runScan().finally(() => { activeScanPromise = null; });
  }

  let scanCancelled = false;
  let scanCancelReason = null;
  // True only for the exact window between our own setTune(true)/setTune
  // (false) calls in the Tune burst below -- everywhere else, a real
  // transmission means something *other* than this scan is keying the
  // radio (WSJT-X auto-sequencing a QSO, the operator hitting Enable Tx/
  // Tune themselves, etc.), which should abort the scan immediately rather
  // than keep band-hopping underneath it.
  let scanOwnTuneActive = false;
  // WSJT-X's own Status broadcast (which currentlyTransmitting is fed from)
  // lags the real over-the-air state slightly -- confirmed live, a real
  // Tune burst's trailing "transmitting: true" broadcast can still arrive
  // a moment after setTune(false) resolves and scanOwnTuneActive is reset,
  // which self-cancelled every real tune burst before this grace period was
  // added (never live-tested with Tune on before -- see git history).
  // Extends tolerance a few seconds past our own tune ending rather than
  // cutting off the instant scanOwnTuneActive flips, without weakening the
  // actual safety guarantee: something genuinely unexpected (a real QSO
  // auto-sequencing, the operator hitting Enable Tx) starting in that exact
  // few-second window is still caught on the very next tick after it does.
  let scanOwnTuneGraceUntilMs = 0;
  const TUNE_STATUS_LAG_GRACE_MS = 4000;

  // Checked on every wait()/waitUntil() tick -- see currentlyTransmitting
  // in applyStatus() above.
  function checkUnexpectedTx() {
    if (scanOwnTuneActive || Date.now() < scanOwnTuneGraceUntilMs) return;
    if (!scanCancelled && currentlyTransmitting) {
      scanCancelled = true;
      scanCancelReason = 'the radio started transmitting';
    }
  }

  // Counts down real seconds, updating findStatus each tick; resolves
  // early (with false) the moment Cancel is clicked, instead of finishing
  // out the full wait -- Cancel needs to feel immediate, not wait 15-30s.
  function wait(seconds, label) {
    return new Promise(resolve => {
      let remaining = seconds;
      (function tick() {
        checkUnexpectedTx();
        if (scanCancelled) { resolve(false); return; }
        findStatus.textContent = `${label} (${remaining}s)`;
        if (remaining <= 0) { resolve(true); return; }
        remaining--;
        setTimeout(tick, 1000);
      })();
    });
  }

  // Waits until an absolute wall-clock deadline (ms since epoch) rather
  // than a fixed duration -- needed to line the Tune burst up with WSJT-X's
  // own 15s decode-cycle grid (real UTC :00/:15/:30/:45 boundaries). A live
  // test showed the old "wait 5 real seconds after the band-switch click
  // returns" approach starting Tune at e.g. 10:17:00 instead of 10:17:05,
  // since that click's return time isn't grid-aligned at all.
  function waitUntil(deadlineMs, label) {
    return new Promise(resolve => {
      (function tick() {
        checkUnexpectedTx();
        if (scanCancelled) { resolve(false); return; }
        const remaining = Math.max(0, deadlineMs - Date.now());
        findStatus.textContent = `${label} (${Math.ceil(remaining / 1000)}s)`;
        if (remaining <= 0) { resolve(true); return; }
        setTimeout(tick, Math.min(1000, remaining));
      })();
    });
  }

  const GRID_MS = 15000; // WSJT-X's own FT8 decode-cycle period

  function nextGridBoundary(fromMs) {
    const mod = fromMs % GRID_MS;
    return mod === 0 ? fromMs : fromMs + (GRID_MS - mod);
  }

  // Retries a postJson() call on network-level failure (fetch() itself
  // throwing -- e.g. "Load failed" from a brief network drop or the Mac
  // sleeping mid-scan) instead of aborting the whole Loop scan over a
  // transient blip. Does NOT retry application-level failures (a JSON
  // {ok: false, ...} response) -- those are real, deterministic errors
  // (e.g. rigctld not connected) that retrying wouldn't fix. Always
  // attempts at least once even if scanCancelled is already true, so the
  // Cancel button's own best-effort Tune-off call (which sets
  // scanCancelled right before calling setTune()) still genuinely tries --
  // it just won't keep retrying after that first attempt fails.
  const RETRY_DELAY_S = 10;

  async function postJsonWithRetry(url, body, label) {
    let attempt = 0;
    while (true) {
      attempt++;
      try {
        return await postJson(url, body);
      } catch (e) {
        if (scanCancelled) throw e;
        for (let remaining = RETRY_DELAY_S; remaining > 0; remaining--) {
          findStatus.textContent = `${label}: network error (${e.message || e}) -- retrying in ${remaining}s (attempt ${attempt})...`;
          await new Promise(r => setTimeout(r, 1000));
          if (scanCancelled) throw e;
        }
      }
    }
  }

  async function tuneToFreq(freqHz) {
    const d = await postJsonWithRetry('/radio/frequency', { frequency_hz: freqHz }, 'Tuning');
    if (!d.ok) throw new Error(d.error || 'Failed to set frequency');
  }

  // -- Reduce power to a safe level before a Tune burst (a real carrier at
  // full power into a mismatched/detuned antenna is the whole reason Tune
  // exists), then restore whatever it actually was before. Best-effort: if
  // reading the current power fails, skip both the reduce and the restore
  // rather than blocking the scan on it -- tuning at whatever power the
  // radio already happens to be at is the pre-existing behaviour, so this
  // only ever makes things safer, never blocks anything that used to work.
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
      // best-effort -- surfaced via the scan status text at the call site
    }
    savedPowerWatts = null;
  }

  async function setTune(on) {
    const d = await postJsonWithRetry('/remote/gui/checkbox', { name: 'Tune', on }, on ? 'Enabling Tune' : 'Disabling Tune');
    if (!d.ok) throw new Error(d.error || `Failed to ${on ? 'enable' : 'disable'} Tune`);
  }

  // Where the very first pass of a Scan should begin: the selected preset
  // that exactly matches the radio's current frequency, else the first
  // selected preset on the radio's current band, else just the start of
  // the list. Only applies to the first pass -- if Loop is on, later
  // passes go start-to-end in the normal order.
  function findScanStartIndex(presets) {
    let idx = presets.findIndex(p => p.freq_hz === currentDialHz);
    if (idx !== -1) return idx;
    if (currentBand) {
      idx = presets.findIndex(p => freqToBand(p.freq_hz) === currentBand);
      if (idx !== -1) return idx;
    }
    return 0;
  }

  async function runScan() {
    const selectedIds = new Set(Array.from(findBandsContainer.querySelectorAll('.find-band'))
      .filter(cb => cb.checked).map(cb => cb.value));
    const selectedPresets = findPresets.filter(p => selectedIds.has(String(p.id)));
    if (selectedPresets.length === 0) { findStatus.textContent = 'Select at least one preset first.'; return; }
    const tuneEachBand = findTuneBox.checked;
    const loopEnabled = findLoopBox.checked;
    const startIndex = findScanStartIndex(selectedPresets);
    let firstPass = true;
    // Captured once, before the first frequency change, so both a natural
    // finish and a Cancel can put the radio back where it actually was --
    // not wherever "before" would mean after several loop passes.
    const originalFreqHz = currentDialHz;

    scanCancelled = false;
    scanCancelReason = null;
    scanOwnTuneActive = false;
    scanOwnTuneGraceUntilMs = 0;
    findScanBtn.disabled = true;
    findCancelBtn.disabled = false;
    setScanningFlag(true);

    let resultText;
    try {
      do {
        const offset = firstPass ? startIndex : 0;
        firstPass = false;
        for (let i = 0; i < selectedPresets.length; i++) {
          const preset = selectedPresets[(offset + i) % selectedPresets.length];
          if (scanCancelled) break;
          const label = `${preset.name} (${(preset.freq_hz / 1e6).toFixed(6)})`;
          // If we're already sitting on this exact frequency (tracked via
          // WSJT-X's own Status broadcasts -- see applyStatus()/currentDialHz
          // above), there's no antenna/tuner mismatch to correct, so skip
          // the Tune burst even if "Tune each band" is checked. Read before
          // tuneToFreq() runs, so it reflects where we actually were, not
          // wherever we're headed.
          const alreadyThere = currentDialHz === preset.freq_hz;
          const doTune = tuneEachBand && !alreadyThere;

          findStatus.textContent = `${label}: tuning to frequency...`;
          await tuneToFreq(preset.freq_hz);
          if (scanCancelled) break;

          if (tuneEachBand && alreadyThere) {
            findStatus.textContent = `${label}: already on this frequency -- skipping tune`;
          }

          if (doTune) {
            // Reduce power *before* computing the grid-aligned tune deadline
            // (not after) so the network round-trip to read/set power
            // doesn't eat into the precisely-timed 5s wait below -- by the
            // time cycleStart is computed, power is already down.
            findStatus.textContent = `${label}: lowering power for tune...`;
            await reducePowerForTune();
            // Tune burst pinned to seconds 5-10 of the *next* grid cycle, so
            // "wait 5 seconds into the interval" means 5 real seconds into an
            // actual WSJT-X decode cycle, not just 5 seconds after whenever
            // tuneToFreq() happened to return. Tune off always runs
            // unconditionally, even if Cancel landed mid-burst (also
            // backstopped by the Cancel button's own handler below).
            const cycleStart = nextGridBoundary(Date.now());
            const reached = await waitUntil(cycleStart + 5000, `${label}: waiting to tune`);
            if (reached && !scanCancelled) {
              findStatus.textContent = `${label}: tuning...`;
              scanOwnTuneActive = true;
              await setTune(true);
              await waitUntil(cycleStart + 10000, `${label}: tuning`);
              await setTune(false);
              await restorePowerAfterTune();
              scanOwnTuneActive = false;
              scanOwnTuneGraceUntilMs = Date.now() + TUNE_STATUS_LAG_GRACE_MS;
              // Ending the tune-off wait at cycleStart+15000 also happens to
              // be the start of the next grid cycle -- "listen starts 5s
              // after tuning completes" and "listen starts on a clean cycle
              // boundary" are the same instant by construction.
              await waitUntil(cycleStart + 15000, `${label}: settling after tune`);
            } else {
              // Cancelled before Tune ever actually engaged -- power may
              // already have been lowered above, so restore it here too.
              await restorePowerAfterTune();
            }
            if (scanCancelled) break;
          } else {
            // No tune happened (toggle off, or already there) -- still snap
            // forward to the next grid boundary before counting listen
            // cycles, so "two complete intervals" means two real, aligned
            // WSJT-X decode cycles rather than an arbitrary 30s window
            // straddling partial ones.
            const boundaryReached = await waitUntil(nextGridBoundary(Date.now()), `${label}: waiting for next cycle`);
            if (!boundaryReached || scanCancelled) break;
          }

          // Regardless of whether this frequency was tuned, always listen
          // for two full 15s intervals before moving on.
          const listened1 = await wait(15, `${label}: listening (1/2)`);
          if (!listened1 || scanCancelled) break;
          const listened2 = await wait(15, `${label}: listening (2/2)`);
          if (!listened2 || scanCancelled) break;
        }
      } while (loopEnabled && !scanCancelled);
      resultText = scanCancelled
        ? (scanCancelReason ? `Scan cancelled: ${scanCancelReason}.` : 'Scan cancelled.')
        : 'Scan complete.';
    } catch (exc) {
      resultText = `Scan stopped: ${exc.message}`;
    } finally {
      // Put the radio back where it actually was before Scan was pressed --
      // for a normal finish as well as a Cancel, per the user's own request.
      if (originalFreqHz) {
        const freqLabel = (originalFreqHz / 1e6).toFixed(6);
        findStatus.textContent = `${resultText} Restoring ${freqLabel}...`;
        try {
          await tuneToFreq(originalFreqHz);
          findStatus.textContent = `${resultText} Back on ${freqLabel}.`;
        } catch (exc) {
          findStatus.textContent = `${resultText} (failed to restore ${freqLabel}: ${exc.message})`;
        }
      } else {
        findStatus.textContent = resultText;
      }
      findScanBtn.disabled = false;
      findCancelBtn.disabled = true;
      setScanningFlag(false);
    }
  }

  function cancelScan() {
    scanCancelled = true;
    findCancelBtn.disabled = true;
    findStatus.textContent = 'Cancelling...';
    // Belt-and-braces: turn Tune off immediately from here too, in case
    // Cancel lands in some timing gap the loop's own cleanup doesn't
    // catch -- leaving a live Tune running unattended is the one outcome
    // that must never happen. Same reasoning for restoring power.
    setTune(false).catch(() => {});
    restorePowerAfterTune().catch(() => {});
    // Also belt-and-braces: don't wait for the loop's own finally block to
    // clear the scanning flag (it will, but only after unwinding through
    // its current wait, up to ~1s) -- a reload landing in that gap should
    // never auto-resume a scan the user just explicitly cancelled.
    setScanningFlag(false);
  }

  findScanBtn.addEventListener('click', startScan);
  findCancelBtn.addEventListener('click', cancelScan);

  return function unmount() {
    intervalIds.forEach(id => clearInterval(id));
    unsubs.forEach(fn => fn());
    // See this file's header comment -- removing a shadow-DOM tile doesn't
    // stop a still-running async scan the way destroying an <iframe>
    // document used to, so explicitly cancel one if it's active. Harmless
    // no-op if nothing's running (cancelScan() is idempotent: Cancel is
    // already disabled once a scan finishes or was never started).
    if (!findCancelBtn.disabled) cancelScan();
  };
}

// -- Registration for the Dashboard applet loader (static/dashboard.html's
// mountApplet()) -- harmless to define even when this file is loaded by a
// real page navigation (full page or standalone widget route) below, it
// just adds two entries to a registry nothing looks at outside /dashboard.
window.DashboardApplets = window.DashboardApplets || {};
['find', 'list'].forEach(mode => {
  window.DashboardApplets['dxm_' + mode] = {
    mount(root, ctx) { return mountLiveEntities(root, ctx, mode); },
  };
});

// -- Standalone feed adapter: same {on, send, onStatus, listenSpectrum,
// unlistenSpectrum} shape as static/dashboard_live.js's
// createDashboardLiveFeed() and static/live_monitor.js's
// createOwnWebSocketFeedAdapter() -- this file doesn't use spectrum at all,
// but keeps the same interface shape so mountLiveEntities never needs to
// know or care which context it's running in. Duplicated rather than
// shared with live_monitor.js's copy since nothing currently imports
// between these files -- revisit if a third family needs the same shape.
function createOwnWebSocketFeedAdapterForDxMonitor() {
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
    // no_history=1 -- this page populates itself from /live/dx_history
    // instead (see mountLiveEntities); without this the server's default
    // /live/ws connect-time replay would deliver every decode a second time.
    ws = new WebSocket(proto + location.host + '/live/ws?no_history=1');
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

// -- Auto-bootstrap for real page navigations only: the full /live/entities
// page and the two standalone /live/entities/widget/* routes all load this
// same file via a normal <script src> tag and expect it to just run,
// exactly as before this refactor. Guarded on dx-entities actually existing
// in `document` so that dashboard.html loading this file purely to
// populate the registry above (its own top-level document has none of
// these ids) no-ops harmlessly instead of throwing on null element lookups.
if (document.getElementById('dx-entities')) {
  mountLiveEntities(document, createOwnWebSocketFeedAdapterForDxMonitor(), document.body.dataset.widgetMode || null);
}

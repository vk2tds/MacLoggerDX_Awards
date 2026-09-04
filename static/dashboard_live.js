// dashboard_live.js -- one shared /live/ws connection for the whole
// Dashboard page, fanned out to however many mounted applets actually want
// it, instead of each iframe-widget opening its own independent connection.
// Opens with no_history=1 deliberately -- a page-wide connection only gets
// a history-replay burst once, at page load, so any applet mounted *later*
// (via "Add widget") would start with empty state if it relied on that
// implicit burst. Each applet is responsible for its own REST catch-up
// fetch on mount instead (e.g. /live/history, /live/dx_history) -- this
// manager is transport + fan-out only, it doesn't know what any given
// applet needs to backfill.
function createDashboardLiveFeed() {
  let ws = null;
  const listeners = {}; // kind -> [cb, ...]
  const statusListeners = []; // cb(connected: bool)
  let spectrumRefcount = 0;
  let connected = false;

  function dispatch(ev) {
    const kind = ev && ev.kind;
    if (!kind || !listeners[kind]) return;
    listeners[kind].slice().forEach(cb => {
      try { cb(ev); } catch (e) { console.error('dashboard_live listener error', e); }
    });
  }

  function setConnected(v) {
    connected = v;
    statusListeners.slice().forEach(cb => {
      try { cb(connected); } catch (e) { console.error('dashboard_live status listener error', e); }
    });
  }

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    ws = new WebSocket(proto + location.host + '/live/ws?no_history=1');
    ws.onopen = () => {
      setConnected(true);
      // Re-subscribe to spectrum data across reconnects if anyone still
      // wants it -- a fresh connection has no memory of the old one's
      // spectrum_listen call.
      if (spectrumRefcount > 0) send({ action: 'spectrum_listen' });
    };
    ws.onmessage = (msg) => {
      let ev;
      try { ev = JSON.parse(msg.data); } catch (e) { return; }
      dispatch(ev);
    };
    ws.onclose = () => { setConnected(false); setTimeout(connect, 2000); };
    ws.onerror = () => ws.close();
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  connect();

  return {
    on(kind, cb) {
      (listeners[kind] = listeners[kind] || []).push(cb);
      return () => {
        listeners[kind] = (listeners[kind] || []).filter(f => f !== cb);
      };
    },
    // Immediately invoked with the current state on subscribe, so a widget
    // mounted after the initial connect (e.g. via "Add widget") shows the
    // right dot right away instead of waiting for the next transition.
    onStatus(cb) {
      statusListeners.push(cb);
      cb(connected);
      return () => {
        const i = statusListeners.indexOf(cb);
        if (i >= 0) statusListeners.splice(i, 1);
      };
    },
    send,
    // Refcounted since live_monitor.py's /live/ws route tracks
    // is_spectrum_listener per *connection* -- with one shared connection,
    // only the first subscriber should actually ask for it, and only the
    // last one leaving should turn it off.
    listenSpectrum() {
      spectrumRefcount++;
      if (spectrumRefcount === 1) send({ action: 'spectrum_listen' });
    },
    unlistenSpectrum() {
      spectrumRefcount = Math.max(0, spectrumRefcount - 1);
      if (spectrumRefcount === 0) send({ action: 'spectrum_unlisten' });
    },
  };
}

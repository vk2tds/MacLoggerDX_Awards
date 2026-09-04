// applets/clock.js -- a big UTC time + date readout, purely client-side
// (no server state involved at all). Unlike every other widget in this
// app, there's no corresponding full page this was split out of -- it was
// built as a mountable applet from the start, see app.py's /clock/widget
// route's docstring. Still gets a real Flask route + minimal template
// (templates/clock_widget.html) so it fits the same fetch-and-mount
// pattern dashboard.html's mountApplet() already uses for everything else,
// and so the URL is directly visitable standalone like any other widget.
function mountUtcClock(root) {
  if (root.host) root.host.setAttribute('data-widget-mode', '');

  const timeEl = root.getElementById('clock-time');
  const dateEl = root.getElementById('clock-date');
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function tick() {
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    timeEl.textContent = `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())} UTC`;
    dateEl.textContent = `${MONTHS[now.getUTCMonth()]} ${now.getUTCDate()}, ${now.getUTCFullYear()}`;
  }
  tick();
  const intervalId = setInterval(tick, 1000);

  return function unmount() {
    clearInterval(intervalId);
  };
}

window.DashboardApplets = window.DashboardApplets || {};
window.DashboardApplets['utc_clock'] = {
  mount(root) { return mountUtcClock(root); },
};

// -- Auto-bootstrap for a real page navigation (opening /clock/widget
// directly in a browser tab) -- see static/live_monitor.js's near-identical
// note for why this guard is needed (dashboard.html loads this file too,
// just to populate the registry above, and its own document has no
// clock-time element for this to accidentally fire against).
if (document.getElementById('clock-time')) {
  mountUtcClock(document);
}

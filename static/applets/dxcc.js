// applets/dxcc.js -- the zero-JS proof of the applet mount mechanism (see
// /Users/darryl/.claude/plans/crystalline-bouncing-meteor.md). DXCC's three
// widgets are pure server-rendered tables with no client-side logic today,
// so there's nothing to wire up here -- dashboard.html's own mountApplet()
// already did the fetch/extract/shadow-attach/stylesheet-adopt work before
// calling mount(); this just has to exist so window.DashboardApplets has an
// entry for these three widget ids instead of falling back to an iframe.
window.DashboardApplets = window.DashboardApplets || {};
['dxcc_stats', 'dxcc_legend', 'dxcc_grid'].forEach(id => {
  window.DashboardApplets[id] = {
    mount(root) {
      // Still needed even for a no-JS-logic widget: dxcc_widget_stats.html
      // has its own [data-widget-mode]-scoped CSS (resize-friendly sizing
      // that shouldn't apply on the full page) -- see near-identical
      // `if (root.host) root.host.setAttribute(...)` in every other
      // family's mount(), e.g. static/live_monitor.js.
      if (root.host) root.host.setAttribute('data-widget-mode', '');
      return function unmount() {};
    },
  };
});

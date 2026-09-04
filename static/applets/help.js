// applets/help.js -- Help's widget is a zero-JS proof exactly like
// applets/dxcc.js: _help_body.html is pure server-rendered <details>/
// <summary> accordions (the browser handles expand/collapse natively, no
// JS needed at all), so there's nothing to wire up here -- dashboard.html's
// own mountApplet() already did the fetch/extract/shadow-attach/stylesheet-
// adopt work before calling mount(); this just has to exist so
// window.DashboardApplets has an entry for this widget id instead of
// falling back to an iframe.
window.DashboardApplets = window.DashboardApplets || {};
window.DashboardApplets['help'] = {
  mount(root) {
    // Still needed for a no-JS-logic widget: templates/help_widget.html
    // sets data-widget-mode="" for consistency with every other family's
    // [data-widget-mode] CSS convention -- see the near-identical note in
    // static/applets/dxcc.js.
    if (root.host) root.host.setAttribute('data-widget-mode', '');
    return function unmount() {};
  },
};

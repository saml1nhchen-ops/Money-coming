/* This separate entry uses the authenticated team backend, never browser vendor keys. */
window.SIGNAL_GEO_MODE = 'team';
if (!location.hash) {
  const teamURL = new URL(location.href);
  teamURL.hash = '/w/demo/overview';
  history.replaceState(null, '', teamURL);
}

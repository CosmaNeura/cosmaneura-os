export const WORKSPACE_LIFECYCLE_CHANNEL = 'cosmas:workspace-lifecycle:v1';
const ENTRY = 'app://cosmas/index.html';

/** One document per app launch. Only an explicit React-ready signal ends startup monitoring. */
export function installDesktopWorkspaceLifecycle({ipcMain, window, fail, timeoutMs = 30_000,
  now = () => performance.now(), setTimer = setTimeout, clearTimer = clearTimeout}) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error('Invalid startup deadline');
  const renderer = window.webContents;
  let disposed = false, started = false, ready = false, failed = false;
  let remaining = timeoutMs, activeSince = null, timer = null, timerGeneration = 0;
  function stopTimer() {
    timerGeneration++;
    if (timer !== null) clearTimer(timer);
    timer = null;
    if (activeSince !== null) remaining -= Math.max(0, now() - activeSince);
    activeSince = null;
  }
  function failOnce(kind) {
    if (disposed || failed) return;
    failed = true; stopTimer();
    void fail(kind);
  }
  function active() {
    return !window.isDestroyed() && window.isVisible() && !window.isMinimized() && window.isFocused();
  }
  function refreshDeadline() {
    stopTimer();
    if (disposed || failed || ready || !started || !active()) return;
    if (remaining <= 0) return failOnce('startup');
    activeSince = now();
    const generation = timerGeneration;
    timer = setTimer(() => {
      if (generation === timerGeneration) refreshDeadline();
    }, remaining);
  }
  function onNavigation(details) {
    if (disposed || failed || details.isMainFrame !== true || details.isSameDocument === true) return;
    // A reload/replacement must not revive the failed document or reuse its privileged session.
    if (started || details.url !== ENTRY) return failOnce(started ? 'renderer' : 'startup');
    started = true; refreshDeadline();
  }
  function onLoadFailure(_event, _code, _description, _url, isMainFrame) {
    if (isMainFrame === true) failOnce(ready ? 'renderer' : 'startup');
  }
  function onNotice(event, kind, ...extra) {
    try {
      if (disposed || failed || !started || renderer.isDestroyed() || event.sender !== renderer ||
          !event.senderFrame || event.senderFrame !== renderer.mainFrame ||
          event.senderFrame.url !== ENTRY || renderer.getURL() !== ENTRY || extra.length !== 0 ||
          (kind !== 'ready' && kind !== 'failed')) return;
      if (kind === 'failed') return failOnce('renderer');
      if (!ready) { ready = true; stopTimer(); }
    } catch { /* A detached frame cannot establish readiness or trigger a different window. */ }
  }
  const onRendererLoss = () => failOnce('renderer');
  ipcMain.on(WORKSPACE_LIFECYCLE_CHANNEL, onNotice);
  renderer.on('did-start-navigation', onNavigation);
  renderer.on('did-fail-load', onLoadFailure);
  renderer.on('render-process-gone', onRendererLoss);
  const activityEvents = ['show', 'hide', 'focus', 'blur', 'minimize', 'restore'];
  for (const event of activityEvents) window.on(event, refreshDeadline);
  function dispose() {
    if (disposed) return;
    disposed = true; stopTimer();
    ipcMain.removeListener(WORKSPACE_LIFECYCLE_CHANNEL, onNotice);
    renderer.removeListener('did-start-navigation', onNavigation);
    renderer.removeListener('did-fail-load', onLoadFailure);
    renderer.removeListener('render-process-gone', onRendererLoss);
    for (const event of activityEvents) window.removeListener(event, refreshDeadline);
    window.removeListener('closed', dispose);
  }
  window.once('closed', dispose);
  return dispose;
}

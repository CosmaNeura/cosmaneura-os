/** Fixed, local guidance only: exception text, paths and workspace data never enter the dialog. */
export function createDesktopFailureHandler({app, dialog, cleanup = () => {}, closeWorkspace = () => true,
  closeTimeoutMs = 5_000, setTimer = setTimeout, clearTimer = clearTimeout}) {
  if (!Number.isFinite(closeTimeoutMs) || closeTimeoutMs <= 0) throw new Error('Invalid renderer closure deadline');
  let pending;
  return function fail(kind = 'startup') {
    if (pending) return pending;
    // Retain one stable promise even if cleanup or destruction reenters this handler.
    let finish;
    pending = new Promise(resolve => { finish = resolve; });
    // End this app's privileged session before waiting for human acknowledgement.
    try { cleanup(); } catch { /* Never expose cleanup exception details. */ }
    // Destroy the owned renderer without an unload prompt. A surviving document must
    // not keep a microphone or pending native callback alive behind a recovery dialog.
    const controller = new AbortController();
    let closeResult = false;
    try { closeResult = closeWorkspace({signal: controller.signal}); } catch { /* Exit below if teardown failed. */ }
    let timer;
    const deadline = new Promise(resolve => {timer = setTimer(() => resolve(false), closeTimeoutMs);});
    void Promise.race([Promise.resolve(closeResult), deadline]).then(async closed => {
      clearTimer(timer); controller.abort();
      // BrowserWindow.destroy() can return before webContents destruction. Never
      // block the native event loop with a dialog until both have been confirmed.
      if (closed !== true) return;
      const renderer = kind === 'renderer';
      // Native app readiness is sufficient for the dialog: no BrowserWindow,
      // persistent renderer session, fallback profile or native helper is opened.
      await app.whenReady();
      dialog.showMessageBoxSync({
        type: 'error', buttons: ['Close CosmasOS'], defaultId: 0, cancelId: 0,
        title: 'CosmasOS recovery', noLink: true,
        message: renderer ? 'Your workspace could not continue.' : 'CosmasOS could not open your workspace.',
        detail: renderer
          ? 'Close and reopen CosmasOS, then review saved work and unconfirmed requests before retrying. Unsaved edits may be missing; submitted work may still finish. If recording was active, review the interruption after reopening. Code: COSMAS_RENDERER_01.'
          : 'Your local work has not been reset. Close and reopen the matching app build, or contact your beta administrator. Do not delete app data. Code: COSMAS_STARTUP_01.',
      });
    }).catch(() => { /* A failed native dialog must not enable a fallback profile or renderer. */ })
      .finally(() => {
        clearTimer(timer); controller.abort();
        try { app.exit(1); } finally { finish(); }
      });
    return pending;
  };
}

/** Force-close only the supplied window; wait for its actual renderer destruction. */
export function destroyDesktopWorkspace(window, {signal} = {}) {
  if (!window) return Promise.resolve(true);
  return new Promise(resolve => {
    let renderer, settled = false;
    function finish(result) {
      if (settled) return;
      settled = true;
      window.removeListener('closed', check);
      renderer?.removeListener('destroyed', check);
      signal?.removeEventListener('abort', abort);
      resolve(result);
    }
    function check() {
      try { if (window.isDestroyed() && renderer.isDestroyed()) finish(true); }
      catch { finish(false); }
    }
    const abort = () => finish(false);
    try {
      renderer = window.webContents;
      if (signal?.aborted) return finish(false);
      window.on('closed', check); renderer.on('destroyed', check);
      signal?.addEventListener('abort', abort, {once: true});
      if (!window.isDestroyed()) window.destroy();
      check();
    } catch { finish(false); }
  });
}

/** Installing this listener also disables Electron's implicit last-window quit. */
export function installDesktopLastWindowPolicy(app, isFailurePending) {
  app.on('window-all-closed', () => { if (!isFailurePending()) app.quit(); });
}

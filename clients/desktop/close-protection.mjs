/** The renderer supplies only its standard unload veto; the main process owns the dialog. */
export function installDesktopCloseProtection(window, dialog) {
  window.webContents.on('will-prevent-unload', event => {
    try {
      const choice = dialog.showMessageBoxSync(window, {
        type: 'warning', buttons: ['Keep working', 'Close anyway'], defaultId: 0, cancelId: 0,
        title: 'Unsaved work', message: 'Close with unsaved or unconfirmed work?',
        detail: 'Closing can lose unsaved text. Work already submitted may still finish. Keep working to save or retry; reopen to check any submitted work.',
        noLink: true,
      });
      // Electron's event is inverted: allowing unload overrides the renderer veto.
      if (choice === 1) event.preventDefault();
    } catch { /* A failed dialog must retain the window and its existing session. */ }
  });
}

export function cleanupOnConfirmedQuit(app, cleanup, {beforeCleanup, onFailure} = {}) {
  let cleaned = false;
  let ready = false, pending = false;
  app.on('will-quit', event => {
    if (cleaned) return;
    if(beforeCleanup&&!ready){
      event.preventDefault();
      // Electron can ignore a quit retried from a microtask while the last
      // window's close event is still unwinding. Resume on the next event turn.
      if(!pending){pending=true;Promise.resolve().then(beforeCleanup).then(()=>{ready=true;pending=false;setImmediate(()=>app.quit());})
        .catch(()=>{pending=false;onFailure?.();});}
      return;
    }
    cleaned = true;
    cleanup();
  });
}

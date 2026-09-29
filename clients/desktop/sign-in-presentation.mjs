/** Return from the separate native sign-in window after its operation settles. */
export function installSignInPresentation(auth, window) {
  let active = true, signingIn = false;
  const remove = auth.subscribe(state => {
    if (!active) return;
    if (state.phase === 'signingIn') { signingIn = true; return; }
    // Background session checks and restored accounts must not steal focus.
    if (!signingIn) return;
    signingIn = false;
    try {
      if (window.isDestroyed() || window.webContents.isDestroyed()) return;
      if (window.isMinimized()) window.restore();
      window.show();
      window.focus();
    } catch { /* Window closure must not alter the authentication result. */ }
  });
  return () => { active = false; signingIn = false; remove(); };
}

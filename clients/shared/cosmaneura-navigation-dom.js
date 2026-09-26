// Runs only in Electron's isolated preload or WKContentWorld.defaultClient.
// The host supplies a private transport; no callable opener enters the page world.
function installCosmaneuraTrustedClicks(available, submit) {
  const consumed = [];
  let pending = false;
  document.addEventListener('click', event => {
    if (!available || pending || !event.isTrusted || event.defaultPrevented || event.button !== 0 || !(event.target instanceof Element)) return;
    const button = event.target.closest('button[data-cosmaneura-record-link],button[data-scheduling-sign-in],button[data-microsoft-connection],button[data-google-connection]');
    if (!(button instanceof HTMLButtonElement) || button.type !== 'button' || button.ownerDocument !== document || !button.isConnected ||
        button.disabled || button.matches(':disabled') || button.closest('[inert]') || button.getAttribute('aria-disabled') === 'true') return;
    const encoded = button.getAttribute('data-cosmaneura-record-link') ?? button.getAttribute('data-scheduling-sign-in') ?? button.getAttribute('data-microsoft-connection') ?? button.getAttribute('data-google-connection');
    if (!encoded || encoded.length > 6144) return;
    let request;
    try { request = JSON.parse(encoded); } catch { return; }
    if (!request || typeof request !== 'object' || Array.isArray(request) ||
        Object.keys(request).sort().join(',') !== 'expectedRevision,href,requestId,schemaVersion' || request.schemaVersion !== 1 ||
        typeof request.requestId !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(request.requestId) ||
        consumed.includes(request.requestId)) return;
    consumed.push(request.requestId); if (consumed.length > 128) consumed.shift();
    pending = true;
    // React's bubble handler may cancel a stale click or commit disabled=true
    // for this accepted click. Respect cancellation without re-reading disabled.
    Promise.resolve().then(() => {
      if (event.defaultPrevented) throw new Error('Unavailable');
      return submit(request);
    }).then(receipt => {
      if (!receipt || Object.keys(receipt).sort().join(',') !== 'requestId,schemaVersion,status' ||
          receipt.schemaVersion !== 1 || receipt.requestId !== request.requestId || receipt.status !== 'opened') throw new Error('Unavailable');
      return receipt;
    }).catch(() => ({schemaVersion: 1, requestId: request.requestId, status: 'unavailable'})).then(receipt => {
      pending = false;
      document.dispatchEvent(new CustomEvent('cosmas-cosmaneura-record-navigation', {detail: JSON.stringify(receipt)}));
    });
  }, true);
}

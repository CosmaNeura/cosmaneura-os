const labels = {
  connected: 'Connected to your local synthetic Box.', sign_in_required: 'Sign in to CosmaBot first.',
  sign_in_unavailable: 'Sign-in unavailable. Check the local development Clerk configuration.',
  sign_in_step_required: 'This sign-in needs another step. This password-only proof cannot complete it.',
  screen_not_recognised: 'Screen not recognised. Open the local invented schedule and try again.',
  request_refused: 'Request refused.', box_unavailable: 'Local Box unavailable. Check the local server and retry.'
};
export function renderResult(document, response) {
  document.querySelector('#status').textContent = labels[response?.state] ?? labels.request_refused;
  const prep = response?.state === 'connected' && typeof response.result?.stub_prep === 'string' ? response.result.stub_prep : '';
  document.querySelector('#prep').textContent = prep;
  document.querySelector('#copy').disabled = !prep;
}

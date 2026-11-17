import {renderResult} from './panel-view.mjs';
let revision = 0;
async function send(message) {
  const current = ++revision;
  renderResult(document, {state: 'sign_in_required'}); // Immediately clear prior prep, including on failure.
  try {
    const response = await chrome.runtime.sendMessage(message);
    if (revision === current) renderResult(document, response);
  } catch { if (revision === current) renderResult(document, {state: 'box_unavailable'}); }
}
document.querySelector('#signin').addEventListener('submit', event => {
  event.preventDefault();
  const password = document.querySelector('#password');
  const message = {type: 'sign-in', identifier: document.querySelector('#identifier').value, password: password.value};
  password.value = '';
  void send(message);
});
for (const [id, type] of [['connect', 'connect'], ['read', 'read-fixture'], ['signout', 'sign-out']])
  document.querySelector(`#${id}`).addEventListener('click', () => void send({type}));
document.querySelector('#copy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(document.querySelector('#prep').textContent); }
  catch { document.querySelector('#status').textContent = 'Copy unavailable. Select the prep text to copy it.'; }
});
void send({type: 'connect'});

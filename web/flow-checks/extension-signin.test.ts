import {describe, expect, it, vi} from 'vitest';
// @ts-expect-error The isolated proof ships plain bundled JavaScript.
import {readScreen} from '../../clients/extension/src/screen.mjs';
// @ts-expect-error The isolated proof ships plain bundled JavaScript.
import {renderResult} from '../../clients/extension/src/panel-view.mjs';
import pack from '../../clients/extension/screen-pack.json';
const fixture = `<table id="invented-schedule"><tbody><tr><td class="appointment">invented-appt</td><td class="person">Taylor Fiction</td><td class="time">09:00</td></tr></tbody></table>`;
const panel = '<p id="status" role="status"></p><pre id="prep"></pre><button id="copy"></button>';

describe('local extension screen and panel', () => {
  it('reads selector data without changing the fixture', () => {
    document.body.innerHTML = fixture;
    const before = document.body.innerHTML;
    expect(readScreen(document, pack)).toEqual({state: 'recognised', rows: [{appointment: 'invented-appt', person: 'Taylor Fiction', time: '09:00'}]});
    expect(document.body.innerHTML).toBe(before);
  });
  it.each(['#absent', '[invalid'])('missing or invalid selector shows a visible state and clears stale copy text: %s', selector => {
    document.body.innerHTML = fixture;
    const response = readScreen(document, {...pack, screen: selector});
    document.body.innerHTML = panel;
    renderResult(document, {state: 'connected', result: {stub_prep: 'old invented prep'}});
    renderResult(document, response);
    expect(document.querySelector('#status')?.textContent).toMatch(/Screen not recognised/);
    expect(document.querySelector('#prep')?.textContent).toBe('');
    expect((document.querySelector('#copy') as HTMLButtonElement).disabled).toBe(true);
  });
  it('missing field, ambiguous field, empty table and executable pack are unrecognised', () => {
    for (const html of [fixture.replace('class="person"', 'class="missing"'), fixture.replace('</tr>', '<td class="person">Ambiguous Fiction</td></tr>'), '<table id="invented-schedule"><tbody></tbody></table>']) {
      document.body.innerHTML = html;
      expect(readScreen(document, pack)).toEqual({state: 'screen_not_recognised'});
    }
    document.body.innerHTML = fixture;
    expect(readScreen(document, {...pack, expression: 'alert(1)'})).toEqual({state: 'screen_not_recognised'});
  });
  it('recovers after a missing selector and renders prep as text', () => {
    document.body.innerHTML = fixture;
    expect(readScreen(document, pack).state).toBe('recognised');
    document.body.innerHTML = panel;
    renderResult(document, {state: 'connected', result: {stub_prep: '<img src=x onerror=alert(1)>'}});
    expect(document.querySelector('#prep img')).toBeNull();
    expect((document.querySelector('#copy') as HTMLButtonElement).disabled).toBe(false);
    renderResult(document, {state: 'sign_in_required'});
    expect(document.querySelector('#prep')?.textContent).toBe('');
  });
});

it('a delayed pre-sign-out response cannot restore prior prep', async () => {
  document.body.innerHTML = panel + '<form id="signin"></form><input id="identifier"><input id="password"><button id="connect"></button><button id="read"></button><button id="signout"></button>';
  let release: (value: unknown) => void = () => {};
  vi.stubGlobal('chrome', {runtime: {sendMessage: vi.fn((message: {type: string}) =>
    message.type === 'connect' ? new Promise(resolve => {release = resolve;}) : Promise.resolve({state: 'sign_in_required'}))}});
  try {
    // @ts-expect-error The isolated proof ships plain bundled JavaScript.
    await import('../../clients/extension/src/panel.mjs');
    (document.querySelector('#signout') as HTMLButtonElement).click();
    await Promise.resolve();
    release({state: 'connected', result: {stub_prep: 'stale invented prep'}});
    await Promise.resolve();
    await Promise.resolve();
    expect(document.querySelector('#status')?.textContent).toMatch(/Sign in to CosmaBot first/);
    expect(document.querySelector('#prep')?.textContent).toBe('');
    expect((document.querySelector('#copy') as HTMLButtonElement).disabled).toBe(true);
  } finally {vi.unstubAllGlobals();}
});

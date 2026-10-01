// Visible-control driver for this local clinician test. No page evaluation,
// application state inspection, API calls, or scripted answers are exposed.
import {chromium} from '@playwright/test';
import {createInterface} from 'node:readline';
import {appendFile, mkdir} from 'node:fs/promises';
import {dirname, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';

const [directory, persona, round, origin = 'http://127.0.0.1:5194'] = process.argv.slice(2);
const reportRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../output');
const output = resolve(directory ?? '');
if (!directory || !output.startsWith(reportRoot + sep) || !['provider', 'nurse', 'pa'].includes(persona) ||
    !['1', '2'].includes(round) || origin !== 'http://127.0.0.1:5194') {
  throw new Error('Use: clinician-live-driver.mjs REPO/output/report-directory provider|nurse|pa 1|2 [http://127.0.0.1:5194]');
}
await mkdir(output, {recursive: true});
const log = resolve(output, 'ui-actions.jsonl');
const browser = await chromium.launch({headless: true});
const context = await browser.newContext({viewport: {width: 1440, height: 1000}, serviceWorkers: 'block'});
await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
const page = await context.newPage();
page.on('dialog', dialog => dialog.dismiss());
const snapshot = () => page.locator('body').ariaSnapshot();
const record = value => appendFile(log, JSON.stringify({at: new Date().toISOString(), persona, round,
  timingKind: 'automated_browser_action_not_human_dwell', ...value}) + '\n');
const locator = command => {
  let target = command.textControl ? page.getByText(command.textControl, {exact: true}) :
    command.label ? page.getByLabel(command.label, {exact: true}) :
      page.getByRole(command.role ?? 'button', {name: command.name, exact: true});
  if (command.index !== undefined) {
    if (!Number.isInteger(command.index) || command.index < 0 || command.index > 50) throw new Error('Use a visible zero-based occurrence.');
    target = target.nth(command.index);
  }
  return target;
};
let sequence = 0;
// PTY canonical mode truncates a pasted transcript-sized JSON line on macOS.
// This is driver transport only; browser controls remain the only action API.
if (process.stdin.isTTY) process.stdin.setRawMode(true);
try {
  await page.goto(`${origin}/?persona=${persona}&round=${round}`, {waitUntil: 'domcontentloaded'});
  await page.getByText('Opening your local clinician test…', {exact: true}).waitFor({state: 'hidden', timeout: 45_000});
  await record({action: 'open', url: page.url()});
  console.log(JSON.stringify({ready: true, url: page.url(), snapshot: await snapshot()}));
  for await (const line of createInterface({input: process.stdin})) {
    const started = performance.now();
    let command, result = {}, outcome = 'completed';
    try {
      command = JSON.parse(line);
      switch (command.action) {
        case 'click': await locator(command).click({timeout: 5000}); break;
        case 'fill': await locator(command).fill(command.text, {timeout: 5000}); break;
        case 'check': await locator(command).setChecked(command.checked ?? true, {timeout: 5000}); break;
        case 'select': await locator(command).selectOption({label: command.option}, {timeout: 5000}); break;
        case 'key': await locator(command).press(command.key, {timeout: 5000}); break;
        case 'scroll':
          await page.mouse.move(command.x ?? 1200, command.y ?? 750);
          await page.mouse.wheel(0, Math.max(-900, Math.min(900, command.dy ?? 500)));
          break;
        case 'reload': await page.reload({waitUntil: 'domcontentloaded'}); break;
        case 'snapshot': break;
        case 'screenshot': {
          if (!/^[a-z0-9_-]+\.png$/.test(command.file)) throw new Error('Use a simple PNG filename.');
          const path = resolve(output, command.file);
          await page.screenshot({path, fullPage: command.fullPage ?? false});
          result = {screenshot: path};
          break;
        }
        case 'close': break;
        default: throw new Error('Unknown visible UI action.');
      }
    } catch (error) { outcome = 'failed'; result = {error: error.message}; }
    const elapsedMs = Math.round(performance.now() - started);
    await record({sequence: ++sequence, action: command?.action ?? 'invalid',
      control: command ? {role: command.role, name: command.name, label: command.label, textControl: command.textControl, index: command.index} : undefined,
      inputCharacters: command?.action === 'fill' && typeof command.text === 'string' ? command.text.length : undefined,
      elapsedMs, outcome, ...result});
    if (command?.action === 'close') { console.log(JSON.stringify({closed: true})); break; }
    console.log(JSON.stringify({sequence, elapsedMs, ...result, url: page.url(), snapshot: await snapshot()}));
  }
} finally { if (process.stdin.isTTY) process.stdin.setRawMode(false); await browser.close(); }

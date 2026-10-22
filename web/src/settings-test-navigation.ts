import {act} from 'react';
import {expect,vi} from 'vitest';

/** Real visible navigation shared by the existing owner/recovery integration suites. */
export function settingsNavigation(container: HTMLElement) {
  const visible = (element: Element) => !element.closest('[hidden]');
  const text = (element: Element) => element.textContent?.replace(/[←→›↗]/g, '').trim();
  async function click(name: string) {
    let button:HTMLButtonElement|undefined;
    // Connection cards wait for their availability read. Re-resolve the control
    // after that read, just as a browser click waits until it is enabled.
    await vi.waitFor(async()=>{
      await act(async()=>{});
      const scope = name === 'Team settings' ? container : container.querySelector('.settings-hub') ?? container;
      button = [...scope.querySelectorAll<HTMLButtonElement>('button')].find(button => visible(button) &&
        (text(button) === name || button.getAttribute('aria-label') === name || [...button.querySelectorAll('strong')].some(child => text(child) === name)));
      expect(button, `Visible settings button: ${name}`).toBeTruthy();
      expect(button!.matches(':disabled'), `Enabled settings button: ${name}`).toBe(false);
    },{timeout:1000});
    await act(async () => button!.click());
  }
  const page = () => container.querySelector('.team-configuration-flow')?.getAttribute('data-page');
  async function team() {
    await click('Team settings');
    const home = [...container.querySelectorAll('.settings-card strong')].find(el => visible(el) && text(el) === 'Your team');
    if (home) await click('Your team');
  }
  async function overview() {
    for (let i = 0; i < 5 && page() !== 'overview'; i++) await click('Back');
    expect(page()).toBe('overview');
  }
  async function practice() { await team(); await overview(); await click('Team preferences'); await click('Practice profile');const disclosure=container.querySelector<HTMLDetailsElement>('.team-practice-editor details');if(disclosure&&!disclosure.open)await act(async()=>disclosure.querySelector('summary')!.click()); }
  async function editSelected(preferredName?:string) {
    const name = preferredName ?? container.querySelector('.team-roster button[aria-pressed="true"] strong')?.textContent ?? 'Visit Prep';
    await team(); await overview();
    const retired = [...container.querySelectorAll('.team-coworker-overview details button')].find(button => text(button) === `${name} · Retired`);
    if (retired) {
      const details = retired.closest('details')!;
      if (!details.open) await act(async () => details.querySelector('summary')!.click());
      await click(`${name} · Retired`);
    } else await click(name);
  }
  async function review() {
    if (page() === 'review') return;
    await overview();
    const initial = [...container.querySelectorAll('button')].some(button => visible(button) && text(button) === 'Use this team');
    await click(initial ? 'Use this team' : 'Review changes');
  }
  async function save() {
    await review();
    const initial = [...container.querySelectorAll('button')].some(button => visible(button) && text(button) === 'Set up my team');
    await click(initial ? 'Set up my team' : 'Save team changes');
  }
  return {click, team, overview, practice, editSelected, review, save, page};
}

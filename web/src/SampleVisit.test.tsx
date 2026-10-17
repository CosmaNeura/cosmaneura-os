import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {WelcomeActions} from './WelcomeActions';

let root:Root,host:HTMLDivElement;
const callbacks={onConnections:vi.fn(),onEncounter:vi.fn(),onResearch:vi.fn(),onRecord:vi.fn(),onRecording:vi.fn()};
beforeEach(async()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();vi.stubGlobal('fetch',vi.fn(()=>{throw new Error('Sample must stay offline');}));host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<WelcomeActions {...callbacks} showConnections connectionsDisabled={false} encounterDisabled={false} encounterLabel="Choose an encounter"/>));});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
const button=(label:string)=>Array.from(host.querySelectorAll<HTMLButtonElement>('button')).find(node=>node.textContent?.includes(label)||node.getAttribute('aria-label')===label)!;
const click=async(label:string)=>{await act(async()=>button(label).click());};
it('offers an immediately usable offline sample without opening an account, recording or encounter',async()=>{
  await click('Try a sample');expect(host.querySelector('[role="dialog"]')).not.toBeNull();expect(host.textContent).toContain('Date of birth: not supplied');expect(host.querySelector<HTMLTextAreaElement>('textarea')!.value).toContain('one-week sleep diary');
  for(const callback of Object.values(callbacks))expect(callback).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
it('requires review and invalidates it when the sample note changes',async()=>{
  await click('Try a sample');expect(button('See the sample handoffs').disabled).toBe(true);
  await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('See the sample handoffs');expect(host.querySelector('[aria-label="Sample team handoffs"]')).not.toBeNull();expect(document.activeElement).toBe(host.querySelector('[aria-label="Sample team handoffs"]'));
  const note=host.querySelector<HTMLTextAreaElement>('textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(note,'Revised sample note');note.dispatchEvent(new Event('input',{bubbles:true}));});
  expect(host.querySelector<HTMLInputElement>('input')!.checked).toBe(false);expect(button('See the sample handoffs').disabled).toBe(true);expect(host.querySelector('[aria-label="Sample team handoffs"]')).toBeNull();expect(fetch).not.toHaveBeenCalled();
});
it('keeps the three entry intents distinct and returns keyboard focus after closing the sample',async()=>{
  await click('Record a visit');expect(callbacks.onRecord).toHaveBeenCalledOnce();expect(callbacks.onRecording).not.toHaveBeenCalled();
  await click('Use an existing recording');expect(callbacks.onRecording).toHaveBeenCalledOnce();
  const launch=button('Try a sample');launch.focus();await click('Try a sample');const dialog=host.querySelector<HTMLElement>('[role="dialog"]')!;expect(document.activeElement).toBe(dialog);
  await act(async()=>dialog.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));expect(host.querySelector('[role="dialog"]')).toBeNull();expect(document.activeElement).toBe(launch);
});
it('keeps the sample available while a practice connection is unavailable',async()=>{
  await act(async()=>root.render(<WelcomeActions {...callbacks} showConnections connectionsDisabled encounterDisabled encounterLabel="Choose an encounter"/>));
  expect(button('Record a visit').disabled).toBe(true);expect(button('Try a sample').disabled).toBe(false);await click('Try a sample');expect(host.querySelector('textarea')).not.toBeNull();
});

it('shows actual prepared agenda, research reference and editable follow-up artifacts without outside actions',async()=>{
  await click('Try a sample');await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('See the sample handoffs');
  expect(host.querySelectorAll('.sample-visit-tasks ol li')).toHaveLength(4);expect(host.querySelector('.sample-visit-tasks a')?.getAttribute('href')).toContain('nhlbi.nih.gov');
  const followup=host.querySelector<HTMLTextAreaElement>('#sample-follow-up')!;expect(followup.value).toContain('one-week sleep diary');
  const checked=host.querySelector<HTMLInputElement>('.sample-visit-tasks input')!;await act(async()=>checked.click());expect(host.textContent).toContain('Sample message reviewed.');
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(followup,'Changed sample message');followup.dispatchEvent(new Event('input',{bubbles:true}));});expect(checked.checked).toBe(false);
  expect(fetch).not.toHaveBeenCalled();for(const callback of Object.values(callbacks))expect(callback).not.toHaveBeenCalled();
});

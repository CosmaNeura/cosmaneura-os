import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_MESSAGES_ENABLED','true');vi.stubEnv('VITE_EHR_READ_ENABLED','true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi} from './workspace-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement;
const visibleButton=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(button=>!button.closest('[hidden]')&&(button.textContent?.trim()===name||button.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
async function wait(check:()=>void){for(let i=0;i<300;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(label:string){await wait(()=>expect(visibleButton(label)?.disabled,label).toBe(false));await act(async()=>{visibleButton(label)!.focus();visibleButton(label)!.click();});}
async function draft(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function openTask(){await click('Details');await click('Review Elation appointment');await wait(()=>expect(visibleButton('Check Elation access')??visibleButton('Restore saved Elation work')).toBeTruthy());}
async function review(){await click('Check Elation access');await click('Load appointments');await wait(()=>expect(host.querySelector<HTMLButtonElement>('ul[aria-label="Appointments"] button')?.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('ul[aria-label="Appointments"] button')!.click());await wait(()=>expect(host.querySelector('[aria-label="Review patient and visit"]')).toBeTruthy());for(const input of host.querySelectorAll<HTMLInputElement>('.ehr-read-panel input[type="checkbox"]'))await act(async()=>input.click());}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);vi.spyOn(workspaceApi,'ask');vi.spyOn(workspaceApi,'append');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
 await wait(()=>expect(host.querySelector<HTMLButtonElement>('.messages-row')?.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row')!.click());await wait(()=>expect(question()?.disabled).toBe(false));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('returns to visible Details without opening the keyboard, keeping one mounted task and the exact draft',async()=>{
 const composer=question();await draft('Keep my Chief directions.');await openTask();const panel=host.querySelector('.ehr-read-panel');await wait(()=>expect(document.activeElement).toBe(host.querySelector('.ehr-read-task h1')));expect(composer.closest('[hidden]')).not.toBeNull();
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(visibleButton('Details')));expect(document.activeElement?.closest('[hidden]')).toBeNull();expect(document.activeElement).not.toBe(composer);expect(question()).toBe(composer);expect(question().value).toBe('Keep my Chief directions.');
 await openTask();expect(host.querySelector('.ehr-read-panel')).toBe(panel);expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
});
it('reviews an appointment from Chief Details, saves it once, and appends source directions to the retained draft without sending',async()=>{
 await draft('Keep the provider’s original directions.');await openTask();await review();await click('Save reviewed appointment');await click('Prepare Chief draft');await wait(()=>expect(question().value).toContain('Review the human-selected Elation'));
 expect(question().value).toContain('Keep the provider’s original directions.');expect(host.querySelector('.ehr-read-task')?.hasAttribute('hidden')).toBe(true);expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
});
it('retains an unconfirmed source save through Back and resolves the same command with zero new appointment reads',async()=>{
 history.replaceState(history.state,'','?scenario=ehr-lost-review'+location.hash);await draft('Keep directions during recovery.');await openTask();await review();await click('Save reviewed appointment');await wait(()=>expect(visibleButton('Check saved source result')).toBeTruthy());
 const stats=()=>Object.assign({},(window as unknown as Window&{ehrRehearsalStats:Record<string,number>}).ehrRehearsalStats),before=stats();expect(before.reads).toBe(2);
 await click('‹ Back to Chief of Staff');await openTask();await click('Restore saved Elation work');await click('Check saved source result');await click('Check Elation access');await wait(()=>expect(visibleButton('Prepare Chief draft')?.disabled).toBe(false));expect(stats().reads).toBe(before.reads);expect(stats().reviews).toBe(before.reviews+1);await click('Prepare Chief draft');await wait(()=>expect(question().value).toContain('Keep directions during recovery.'));expect(workspaceApi.ask).not.toHaveBeenCalled();
});
it('returns to the saved-sources entry control after opening the same task from Sources',async()=>{
 await draft('Retain the visit instructions.');await click('Details');await click('Saved sources');await click('Review Elation appointment');await wait(()=>expect(visibleButton('Check Elation access')).toBeTruthy());await click('‹ Back to saved sources');await wait(()=>expect(document.activeElement).toBe(visibleButton('Review Elation appointment')));expect(document.activeElement?.closest('[hidden]')).toBeNull();expect(question().value).toBe('Retain the visit instructions.');
});
it('consumes browser Back to dismiss the task without losing the Chief conversation or its pending draft',async()=>{
 await draft('Keep this browser Back draft.');await openTask();const origin=location.hash;
 await act(async()=>{history.replaceState(history.state,'','#cosmas/home');window.dispatchEvent(new PopStateEvent('popstate'));});
 await wait(()=>expect(host.querySelector('.ehr-read-task')?.hasAttribute('hidden')).toBe(true));expect(location.hash).toBe(origin);expect(question().value).toBe('Keep this browser Back draft.');expect(workspaceApi.ask).not.toHaveBeenCalled();
});
async function delayedOpening(){
 const result=await workspaceApi.team(identity);let release!:()=>void;
 vi.spyOn(workspaceApi,'team').mockImplementationOnce(()=>new Promise(resolve=>{release=()=>resolve(result);}));
 await click('Review Elation appointment');await wait(()=>expect(release).toBeTypeOf('function'));
 return async()=>{await act(async()=>{release();});};
}
it.each(['Escape','Saved sources'] as const)('does not reopen Elation after %s wins during opening authorization',async choice=>{
 await draft('Keep the original directions.');await click('Details');const finish=await delayedOpening();
 if(choice==='Escape')await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
 else await click('Saved sources');
 await finish();expect(host.querySelector('.ehr-read-task')).toBeNull();expect(question().value).toBe('Keep the original directions.');
 expect(document.activeElement?.closest('[hidden]')).toBeNull();expect(workspaceApi.ask).not.toHaveBeenCalled();
 if(choice==='Escape')expect(visibleButton('Details')).toBeTruthy();else expect(visibleButton('Review Elation appointment')).toBeTruthy();
});
it('does not open Elation after leaving the source entry during authorization',async()=>{
 await click('Details');await click('Saved sources');const finish=await delayedOpening();await click('Open notebook');await finish();
 expect(host.querySelector('.ehr-read-task')).toBeNull();expect(visibleButton('Review Elation appointment')).toBeUndefined();expect(workspaceApi.ask).not.toHaveBeenCalled();
});
it('does not open Elation after leaving its connection entry during authorization',async()=>{
 await click('Settings');
 const connections=[...host.querySelectorAll<HTMLButtonElement>('.settings-cards button')].find(button=>button.querySelector('strong')?.textContent==='Connections')!;
 await act(async()=>connections.click());
 await wait(()=>expect(host.querySelector<HTMLButtonElement>('[aria-label="Practice records"] button')?.disabled).toBe(false));
 await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="Practice records"] button')!.click());
 const finish=await delayedOpening();await click('← All connections');await finish();
 expect(host.querySelector('.ehr-read-task')).toBeNull();expect(host.querySelector('.settings-hub h1')?.textContent).toBe('Connections');expect(workspaceApi.ask).not.toHaveBeenCalled();
});

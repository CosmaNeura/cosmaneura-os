import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_EHR_READ_ENABLED','VITE_CALENDAR_IMPORT_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {ehrReadApi} from './ehr-read-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement;
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name||b.querySelector('strong')?.textContent===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question');
const task=()=>[...host.querySelectorAll<HTMLElement>('.ehr-read-task')].find(visible);
async function wait(check:()=>void){for(let n=0;n<300;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(name:string){await wait(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>{button(name)!.focus({preventScroll:true});button(name)!.click();});}
async function openChat(){if(question()&&visible(question()!)&&!question()!.disabled)return;const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(b=>visible(b)&&b.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()?.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(question()?.disabled).toBe(false));}
async function records(){await click('Settings');await click('Connections');await click('Add connection');}
async function selectVisit(){const row=()=>host.querySelector<HTMLButtonElement>('.team-encounter-picker .team-encounter-option');await wait(()=>expect(row()?.disabled).toBe(false));await act(async()=>row()!.click());}
async function choose(provider:string){const target=host.querySelector<HTMLButtonElement>(`[data-practice-record-provider="${provider}"]`);expect(target).not.toBeNull();expect(target!.disabled).toBe(false);await act(async()=>{target!.focus({preventScroll:true});target!.click();});return target!;}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);vi.spyOn(workspaceApi,'ask');vi.spyOn(workspaceApi,'append');vi.spyOn(ehrReadApi,'execute');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('keeps the original unauthenticated synthetic workspace usable without a records owner',async()=>{
 await act(async()=>root.render(<EncounterWorkspace draftStorage={memoryDraftStorage()}/>));expect(host.querySelector('.team-workspace')).not.toBeNull();expect(task()).toBeUndefined();
});
it.each(['elation','tebra','athena','atlas_md'])('opens the existing %s task from Connections and keeps the exact Chief draft',async provider=>{
 await openChat();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),'Keep my original Chief directions.');question()!.dispatchEvent(new Event('input',{bubbles:true}));});await click('‹ Messages');await records();const target=await choose(provider);
 await wait(()=>expect(task()).toBeDefined());
 if(provider==='atlas_md')expect(task()?.textContent).toContain('Import calendar file');else await wait(()=>expect(task()?.querySelector<HTMLSelectElement>('[aria-label="Records system"]')?.value).toBe(provider));
 await click('‹ Back to connections');await wait(()=>expect(document.activeElement).toBe(target.isConnected&&visible(target)?target:host.querySelector('.settings-hub-heading h1')));expect(task()).toBeUndefined();await click('Done');await openChat();expect(question()?.value).toBe('Keep my original Chief directions.');expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it.each(['athena','atlas_md'])('retains the selected %s provider through the existing visit picker',async provider=>{
 await records();await choose(provider);await selectVisit();await wait(()=>expect(task()).toBeDefined());
 if(provider==='atlas_md')expect(task()?.textContent).toContain('Import calendar file');else await wait(()=>expect(task()?.querySelector<HTMLSelectElement>('[aria-label="Records system"]')?.value).toBe(provider));
 await click('‹ Back to connections');await wait(()=>expect(document.activeElement).toBe(host.querySelector('.settings-hub-heading h1')));expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it('discarding the visit picker does not later replay a vendor launch',async()=>{
 await records();await choose('tebra');await wait(()=>expect(host.querySelector<HTMLButtonElement>('.team-encounter-option')?.disabled).toBe(false));await click('Messages');await openChat();expect(task()).toBeUndefined();await click('Details');await click('Review EHR records');await wait(()=>expect(task()?.querySelector<HTMLSelectElement>('[aria-label="Records system"]')?.value).toBe('elation'));
});
it('a denied opening cannot publish the requested provider or leave Connections',async()=>{
 await openChat();await click('‹ Messages');await records();vi.spyOn(workspaceApi,'team').mockRejectedValueOnce(new WorkspaceApiError(403));await choose('tebra');await wait(()=>expect(task()).toBeUndefined());expect(ehrReadApi.execute).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
});
it('a failed discovery does not attach its vendor to a later ordinary visit opening',async()=>{
 await records();const catalog=vi.spyOn(workspaceApi,'catalog').mockRejectedValueOnce(new WorkspaceApiError(503));await choose('tebra');await wait(()=>expect(catalog).toHaveBeenCalledOnce());await click('Visits');await selectVisit();await wait(()=>expect(host.querySelector('.team-workspace')?.getAttribute('data-page')).toBe('notebook'));await act(async()=>new Promise<void>(resolve=>requestAnimationFrame(()=>resolve())));expect(task()).toBeUndefined();expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it('an abandoned discovery cannot attach its late result to another visit choice',async()=>{
 await records();const visits=await workspaceApi.catalog(identity);let release!:(value:typeof visits)=>void;vi.spyOn(workspaceApi,'catalog').mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));await choose('athena');await wait(()=>expect(release).toBeTypeOf('function'));await click('Messages');await act(async()=>release(visits));await click('Visits');await selectVisit();await wait(()=>expect(host.querySelector('.team-workspace')?.getAttribute('data-page')).toBe('notebook'));await act(async()=>new Promise<void>(resolve=>requestAnimationFrame(()=>resolve())));expect(task()).toBeUndefined();expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it.each(['suspension','history navigation'])('a retained picker-return frame cannot launch records after %s',async interruption=>{
 await records();await choose('athena');await wait(()=>expect(host.querySelector<HTMLButtonElement>('.team-encounter-option')?.disabled).toBe(false));const frames:FrameRequestCallback[]=[];
 vi.spyOn(window,'requestAnimationFrame').mockImplementation(callback=>{frames.push(callback);return frames.length+70000;});await selectVisit();await wait(()=>expect(frames.length).toBeGreaterThan(0));
 await act(async()=>{if(interruption==='suspension')window.dispatchEvent(new Event('pagehide'));else{history.replaceState(null,'','#cosmas/home');window.dispatchEvent(new PopStateEvent('popstate'));}});
 if(interruption==='history navigation'){await click('Settings');await click('Connections');}
 await act(async()=>{for(const frame of [...frames])frame(0);});expect(task()).toBeUndefined();expect(ehrReadApi.execute).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
});

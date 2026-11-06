import {act} from 'react';
import {waitMessagesJourney as wait, MESSAGES_JOURNEY_TEST_TIMEOUT_MS} from './messages-journey-wait';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_EHR_READ_ENABLED','VITE_CALENDAR_IMPORT_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
const observed=vi.hoisted(()=>({session:null as import('./session/workspace-session').WorkspaceSession|null}));
vi.mock('./session/use-workspace-session',async original=>{const value=await original<typeof import('./session/use-workspace-session')>();return {...value,useWorkspaceSession:(...args:Parameters<typeof value.useWorkspaceSession>)=>{observed.session=args[0];return value.useWorkspaceSession(...args);}};});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {ehrReadApi} from './ehr-read-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');

// Journey waits may legitimately exceed Vitest's 5s default under CI load.
vi.setConfig({testTimeout: MESSAGES_JOURNEY_TEST_TIMEOUT_MS});
let root:Root,host:HTMLDivElement;
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name||b.querySelector('strong')?.textContent===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question');
const task=()=>[...host.querySelectorAll<HTMLElement>('.ehr-read-task')].find(visible);
const picker=()=>[...host.querySelectorAll<HTMLElement>('.team-welcome')].find(visible);

async function click(name:string){await wait(()=>expect(button(name)).toBeTruthy());await wait(()=>expect(button(name)!.disabled).toBe(false));await act(async()=>{button(name)!.focus({preventScroll:true});button(name)!.click();});}
async function openChat(){if(question()&&visible(question()!)&&!question()!.disabled)return;const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(b=>visible(b)&&b.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()).toBeTruthy());await wait(()=>expect(row()!.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(question()).toBeTruthy());await wait(()=>expect(question()!.disabled).toBe(false));}
async function records(){await click('Settings');await click('Connections');await click('Add connection');}
async function selectVisit(){const row=()=>host.querySelector<HTMLButtonElement>('.team-encounter-picker .team-encounter-option');await wait(()=>expect(row()).toBeTruthy());await wait(()=>expect(row()!.disabled).toBe(false));await act(async()=>row()!.click());}
async function choose(provider:string){const target=host.querySelector<HTMLButtonElement>(`[data-practice-record-provider="${provider}"]`);expect(target).not.toBeNull();expect(target!.disabled).toBe(false);await act(async()=>{target!.focus({preventScroll:true});target!.click();});return target!;}
const recordsSystem=(root?:ParentNode|null)=>{const text=[...(root?.querySelectorAll<HTMLButtonElement>('[role="group"][aria-label="Records system"] button')??[])].find(b=>b.getAttribute('aria-pressed')==='true')?.textContent;return {Elation:'elation',Tebra:'tebra',Athena:'athena'}[text??''];};
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);vi.spyOn(workspaceApi,'ask');vi.spyOn(workspaceApi,'append');vi.spyOn(ehrReadApi,'execute');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('keeps the original unauthenticated synthetic workspace usable without a records owner',async()=>{
 await act(async()=>root.render(<EncounterWorkspace draftStorage={memoryDraftStorage()}/>));expect(host.querySelector('.team-workspace')).not.toBeNull();expect(task()).toBeUndefined();
});
it.each([['elation','Open Elation records'],['atlas_md','Import Atlas.MD calendar file']] as const)('opens the %s task from EHR and Rx Relay and keeps the exact Chief draft',async (provider,action)=>{
 await openChat();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),'Keep my original Chief directions.');question()!.dispatchEvent(new Event('input',{bubbles:true}));});await click('‹ Messages');await click('Settings');await click('EHR & Rx Relay');
 if(provider==='atlas_md')await click('Atlas.MD');
 await click(action);await wait(()=>expect(task()).toBeDefined());
 if(provider==='atlas_md')expect(task()?.textContent).toContain('Import calendar file');else await wait(()=>expect(recordsSystem(task())).toBe(provider));
 await click('‹ Back to connections');expect(task()).toBeUndefined();await click('Done');await openChat();expect(question()?.value).toBe('Keep my original Chief directions.');expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it.each(['elation','tebra','athena','atlas_md'])('opens the existing %s task from Connections and keeps the exact Chief draft',async provider=>{
 await openChat();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),'Keep my original Chief directions.');question()!.dispatchEvent(new Event('input',{bubbles:true}));});await click('‹ Messages');await records();const target=await choose(provider);
 await wait(()=>expect(task()).toBeDefined());
 if(provider==='atlas_md')expect(task()?.textContent).toContain('Import calendar file');else await wait(()=>expect(recordsSystem(task())).toBe(provider));
 await click('‹ Back to connections');await wait(()=>expect(document.activeElement).toBe(target.isConnected&&visible(target)?target:host.querySelector('.settings-hub-heading h1')));expect(task()).toBeUndefined();await click('Done');await openChat();expect(question()?.value).toBe('Keep my original Chief directions.');expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it.each([['elation','Elation records'],['tebra','Tebra records'],['athena','athenahealth records'],['atlas_md','Atlas.MD calendar import']])('retains the selected %s provider and purpose through the existing visit picker',async (provider,purpose)=>{
 await records();await choose(provider);await wait(()=>expect(picker()?.querySelector('h1')?.textContent).toBe(`Choose a visit for ${purpose}`));expect(button('Return to connections')?.disabled).toBe(false);expect(picker()?.textContent).not.toContain('Record a visit, or open its notes.');
 if(provider==='atlas_md')expect(picker()?.textContent).toContain('Next, select and review a calendar file before importing it.');else expect(picker()?.textContent).toContain('Next, check the connection and choose records to review.');
 expect([...picker()!.querySelectorAll('.visit-catalog-tabs button')].map(item=>item.textContent)).not.toContain('Unlinked notes');expect(picker()?.querySelector('.team-record-visit')).toBeNull();expect(ehrReadApi.execute).not.toHaveBeenCalled();await selectVisit();await wait(()=>expect(task()).toBeDefined());
 if(provider==='atlas_md')expect(task()?.textContent).toContain('Import calendar file');else await wait(()=>expect(recordsSystem(task())).toBe(provider));
 await click('‹ Back to connections');await wait(()=>expect(document.activeElement).toBe(host.querySelector('.settings-hub-heading h1')));expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it('returns from records visit selection to Connections with the exact unsent private Chief draft, then discards the cancelled intent',async()=>{
 await click('New message');const chief=()=>host.querySelector<HTMLButtonElement>('.messages-bot-choices button:nth-child(1)');await wait(()=>expect(chief()?.textContent).toContain('Chief of Staff'));await act(async()=>chief()!.click());const start=()=>host.querySelector<HTMLButtonElement>('.practice-quick-start button[type="submit"]');await wait(()=>expect(start()?.disabled).toBe(false));await act(async()=>start()!.click());await wait(()=>expect(question()?.disabled).toBe(false));
 const composer=question()!,directions='Keep these invented private Chief directions.';await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(composer,directions);composer.dispatchEvent(new Event('input',{bubbles:true}));});await click('‹ Messages');await records();await choose('tebra');await wait(()=>expect(picker()?.querySelector('h1')?.textContent).toBe('Choose a visit for Tebra records'));
 const pending={type:'entry' as const,body:{kind:'scratchpad' as const,content:'An existing invented pending write',expected_revision:observed.session!.getSnapshot().workspace!.revision,idempotency_key:'20000000-0000-4000-8000-000000000002'}};
 await act(async()=>observed.session!.setPending(pending));expect(button('Return to connections')?.disabled).toBe(true);expect(button('Refresh visits')?.disabled).toBe(true);await act(async()=>button('Return to connections')!.click());expect(observed.session!.getSnapshot().settingsOpen).toBe(false);expect(observed.session!.getSnapshot().pending).toBe(pending);expect(composer.value).toBe(directions);
 await act(async()=>observed.session!.setPending(null));await click('Return to connections');expect(host.querySelector('.settings-hub-heading h1')?.textContent).toBe('Connections');expect(task()).toBeUndefined();await click('Done');await click('Current notebook');await wait(()=>expect(question()?.closest('[hidden]')).toBeNull());expect(question()).toBe(composer);expect(composer.value).toBe(directions);
 await click('Visits');await wait(()=>expect(picker()?.querySelector('h1')?.textContent).toBe('Your encounters'));await selectVisit();expect(task()).toBeUndefined();expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it('selects an Elation destination, saves the reviewed appointment once, and prepares the Chief source question without sending',async()=>{
 const review=vi.spyOn(ehrReadApi,'review');await records();await choose('elation');await wait(()=>expect(picker()?.querySelector('h1')?.textContent).toBe('Choose a visit for Elation records'));await click('Refresh visits');expect(picker()?.querySelector('h1')?.textContent).toBe('Choose a visit for Elation records');await selectVisit();await click('Check Elation access');await click('Load appointments');const appointment=()=>task()?.querySelector<HTMLButtonElement>('ul[aria-label="Appointments"] button');await wait(()=>expect(appointment()?.disabled).toBe(false));await act(async()=>appointment()!.click());await wait(()=>expect(task()?.querySelector('[aria-label="Review patient and visit"]')).toBeTruthy());for(const input of task()!.querySelectorAll<HTMLInputElement>('.ehr-read-panel input[type="checkbox"]'))await act(async()=>input.click());await click('Save reviewed appointment');await wait(()=>expect(button('Prepare Chief draft')?.disabled).toBe(false));
 expect(review).toHaveBeenCalledOnce();const saved=await review.mock.results[0].value;await click('Prepare Chief draft');await wait(()=>expect(question()?.closest('[hidden]')).toBeNull());expect(question()?.value).toContain(`Review the human-selected EHR source ${saved.entry_id}`);expect(task()).toBeUndefined();expect(ehrReadApi.execute).toHaveBeenCalledTimes(2);expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();expect((window as unknown as {ehrRehearsalStats:{externalCalls:number}}).ehrRehearsalStats.externalCalls).toBe(0);
});
it.each(['owner','workspace','generation'])('discards the contextual picker action after its %s changes',async change=>{
 await records();await choose('elation');await wait(()=>expect(picker()?.querySelector('h1')?.textContent).toBe('Choose a visit for Elation records'));const old=button('Return to connections')!,oldRefresh=button('Refresh visits')!,catalog=vi.spyOn(workspaceApi,'catalog');
 await act(async()=>{if(change==='generation'){observed.session!.generation.current++;observed.session!.setMessage('Synthetic generation changed.');}else if(change==='workspace'){const visit=(await workspaceApi.catalog(identity))[0];const opened=await workspaceApi.open(identity,visit.appointment_id);observed.session!.setWorkspace(opened.workspace);}else await root.render(<EncounterWorkspace authenticated={{...identity}} draftStorage={memoryDraftStorage()}/>);});const calls=catalog.mock.calls.length;await act(async()=>{old.click();oldRefresh.click();});expect(observed.session!.getSnapshot().settingsOpen).toBe(false);expect(picker()?.querySelector('h1')?.textContent).not.toBe('Choose a visit for Elation records');expect(catalog).toHaveBeenCalledTimes(calls);expect(ehrReadApi.execute).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
});
it('discarding the visit picker does not later replay a vendor launch',async()=>{
 await records();await choose('tebra');await wait(()=>expect(host.querySelector<HTMLButtonElement>('.team-encounter-option')).toBeTruthy());await wait(()=>expect(host.querySelector<HTMLButtonElement>('.team-encounter-option')!.disabled).toBe(false));await click('Chats');await openChat();expect(task()).toBeUndefined();await click('Details');await click('Choose notes or sources');await click('Review EHR records');await wait(()=>expect(recordsSystem(task())).toBe('elation'));
});
it('a denied opening cannot publish the requested provider or leave Connections',async()=>{
 await openChat();await click('‹ Messages');await records();vi.spyOn(workspaceApi,'team').mockRejectedValueOnce(new WorkspaceApiError(403));await choose('tebra');await wait(()=>expect(task()).toBeUndefined());expect(ehrReadApi.execute).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
});
it('a failed discovery does not attach its vendor to a later ordinary visit opening',async()=>{
 await records();const catalog=vi.spyOn(workspaceApi,'catalog').mockRejectedValueOnce(new WorkspaceApiError(503));await choose('tebra');await wait(()=>expect(catalog).toHaveBeenCalledOnce());await click('Visits');await selectVisit();await wait(()=>expect(host.querySelector('.team-workspace')?.getAttribute('data-page')).toBe('notebook'));await act(async()=>new Promise<void>(resolve=>requestAnimationFrame(()=>resolve())));expect(task()).toBeUndefined();expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it('an abandoned discovery cannot attach its late result to another visit choice',async()=>{
 await records();const visits=await workspaceApi.catalog(identity);let release!:(value:typeof visits)=>void;vi.spyOn(workspaceApi,'catalog').mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));await choose('athena');await wait(()=>expect(release).toBeTypeOf('function'));await click('Chats');await act(async()=>release(visits));await click('Visits');await selectVisit();await wait(()=>expect(host.querySelector('.team-workspace')?.getAttribute('data-page')).toBe('notebook'));await act(async()=>new Promise<void>(resolve=>requestAnimationFrame(()=>resolve())));expect(task()).toBeUndefined();expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
it.each(['suspension','history navigation'])('a retained picker-return frame cannot launch records after %s',async interruption=>{
 await records();await choose('athena');await wait(()=>expect(host.querySelector<HTMLButtonElement>('.team-encounter-option')).toBeTruthy());await wait(()=>expect(host.querySelector<HTMLButtonElement>('.team-encounter-option')!.disabled).toBe(false));const frames:FrameRequestCallback[]=[];
 vi.spyOn(window,'requestAnimationFrame').mockImplementation(callback=>{frames.push(callback);return frames.length+70000;});await selectVisit();await wait(()=>expect(frames.length).toBeGreaterThan(0));
 await act(async()=>{if(interruption==='suspension')window.dispatchEvent(new Event('pagehide'));else{history.replaceState(null,'','#cosmas/home');window.dispatchEvent(new PopStateEvent('popstate'));}});
 if(interruption==='history navigation'){await click('Settings');await click('Connections');}
 await act(async()=>{for(const frame of [...frames])frame(0);});expect(task()).toBeUndefined();expect(ehrReadApi.execute).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
});

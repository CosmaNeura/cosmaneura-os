import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_CORE_CONNECTION_ENABLED','VITE_ATHENA_CONNECTION_ENABLED','VITE_ATHENA_VISIT_LINK_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi} from './workspace-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
import {useUnsavedWork} from './unsaved-work';
import {readinessFixture} from './connection-readiness-fixture';
import {CONNECTION_IDS} from './connection-catalog-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement;
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
async function wait(check:()=>void){for(let n=0;n<350;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(label:string){await wait(()=>expect(button(label)?.disabled,label).toBe(false));await act(async()=>{button(label)!.focus();button(label)!.click();});}
async function clickCard(name:string){await wait(()=>expect([...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&b.querySelector('strong')?.textContent===name)?.disabled).toBe(false));await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&b.querySelector('strong')?.textContent===name)!.click());}
async function draft(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function connect(){
 for(const label of ['Check connection status','Check Athena connection','View Athena appointments','Connect or open visit','Find Cosmaneura visits','Review this visit'])await click(label);
 const confirmation=()=>host.querySelector<HTMLInputElement>('.ehr-read-task[aria-label="Find or connect an Athena visit"] input[type="checkbox"]');
 await wait(()=>expect(confirmation()?.matches(':disabled')).toBe(false));await act(async()=>confirmation()!.click());expect(confirmation()?.checked).toBe(true);await click('Save visit connection');
}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);vi.spyOn(workspaceApi,'ask');vi.spyOn(workspaceApi,'append');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
 await wait(()=>expect(host.querySelector<HTMLButtonElement>('.messages-row')?.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row')!.click());await wait(()=>expect(question()?.disabled).toBe(false));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('opens the shared Athena task from Chief and Settings while keeping the exact draft and one host',async()=>{
 await draft('Keep my Chief directions verbatim.');const composer=question();await click('Details');await click('Find or connect an Athena visit');
 await wait(()=>expect(button('Check connection status')).toBeDefined());const task=host.querySelector('[aria-label="Find or connect an Athena visit"]');expect(task?.textContent).toContain('Jordan');expect(composer.closest('[hidden]')).not.toBeNull();
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(button('Details')));expect(question()).toBe(composer);expect(question().value).toBe('Keep my Chief directions verbatim.');
 // This path requires an enabled Core service; the shared email fixture intentionally reports practice setup.
 const originalFetch=window.fetch,catalog=readinessFixture({core:'user_connectable'});
 vi.spyOn(window,'fetch').mockImplementation(async(input,init)=>new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,location.href).pathname==='/connections/catalog'
  ?new Response(JSON.stringify({version:2,services:CONNECTION_IDS.map(id=>({id,setup_available:catalog[id],...catalog.readiness![id]}))}),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})
  :originalFetch(input,init));
 await click('Settings');await clickCard('Connections');await clickCard('Cosmaneura account & appointments');await click('Find or connect an Athena visit');
 await wait(()=>expect(button('Check connection status')).toBeDefined());expect(host.querySelector('[aria-label="Find or connect an Athena visit"]')).toBe(task);await click('‹ Back to connections');
 await wait(()=>expect(button('Find or connect an Athena visit')).toBeDefined());expect(question().value).toBe('Keep my Chief directions verbatim.');expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
});
it.each(['fresh','recovered'] as const)('does not open a %s notebook selection while Chief has unfinished text',async mode=>{
 const open=vi.spyOn(workspaceApi,'openExisting');
 if(mode==='recovered')history.replaceState(null,'','/?scenario=athena-lost-link'+location.hash);
 await draft('Unsent Chief question.');await click('Details');await click('Find or connect an Athena visit');
 await connect();
 if(mode==='recovered'){await click('Check saved visit result');await wait(()=>expect(host.textContent).toContain('Connected to Jordan Cypress'));}
 await wait(()=>expect(button('Open linked notebook')?.disabled).toBe(true));expect(host.textContent).toContain('Save or recover unfinished work');await click('‹ Back to Chief of Staff');expect(question().value).toBe('Unsent Chief question.');
 expect(open).not.toHaveBeenCalled();
});
it.each(['fresh','recovered'] as const)('opens the already-current notebook from a clean %s selection and closes the task',async mode=>{
 const saved=sessionStorage.getItem('cosmabot-desktop-ux-acceptance-v1');expect(saved).not.toBeNull();const current=JSON.parse(saved!) as {id:string};
 expect(location.hash).toContain(current.id);
 const open=vi.spyOn(workspaceApi,'openExisting');
 if(mode==='recovered')history.replaceState(null,'','/?scenario=athena-lost-link'+location.hash);
 await click('Details');await click('Find or connect an Athena visit');await connect();
 if(mode==='recovered'){await click('Check saved visit result');await wait(()=>expect(host.textContent).toContain('Connected to Jordan Cypress'));}
 await wait(()=>expect(button('Open linked notebook')?.disabled).toBe(false));
 const original=workspaceApi.team;let finish!:()=>void,started!:()=>void;const entered=new Promise<void>(resolve=>{started=resolve;});
 vi.spyOn(workspaceApi,'team').mockImplementationOnce(async(...args)=>{started();await new Promise<void>(resolve=>{finish=resolve;});return original(...args);});
 await click('Open linked notebook');await entered;expect(open).not.toHaveBeenCalled();
 await act(async()=>{finish();});await wait(()=>expect(open).toHaveBeenCalledOnce());
 await wait(()=>expect(host.querySelector('[aria-label="Find or connect an Athena visit"]')?.closest('[hidden]')).not.toBeNull());
 expect(question().value).toBe('');expect(question().closest('[hidden]')).toBeNull();
 expect(open.mock.calls[0][0]).toBe(identity);expect(open.mock.calls[0][1].workspace_id).toBe(current.id);
});
it('keeps unrelated unsaved work admission after the Athena authorization finishes',async()=>{
 history.replaceState(null,'','/?scenario=athena-lost-link'+location.hash);
 await click('Details');await click('Find or connect an Athena visit');await connect();await click('Check saved visit result');
 await wait(()=>expect(button('Open linked notebook')?.disabled).toBe(false));
 const open=vi.spyOn(workspaceApi,'openExisting'),original=workspaceApi.team;let finish!:()=>void,started!:()=>void;const entered=new Promise<void>(resolve=>{started=resolve;});
 vi.spyOn(workspaceApi,'team').mockImplementationOnce(async(...args)=>{started();await new Promise<void>(resolve=>{finish=resolve;});return original(...args);});
 await click('Open linked notebook');await entered;
 function OtherUnfinishedEditor(){useUnsavedWork(true);return null;}
 const otherHost=document.createElement('div'),otherRoot=createRoot(otherHost);document.body.append(otherHost);
 try{
  await act(async()=>otherRoot.render(<OtherUnfinishedEditor/>));await act(async()=>finish());
  await wait(()=>expect(host.textContent).toContain('Save or recover unfinished work before opening a notebook.'));
  expect(open).not.toHaveBeenCalled();expect(button('Open linked notebook')?.disabled).toBe(true);
 }finally{await act(async()=>otherRoot.unmount());otherHost.remove();}
});
it('shows an opening failure in the active task and retries only notebook opening',async()=>{
 history.replaceState(null,'','/?scenario=athena-lost-link'+location.hash);
 await click('Details');await click('Find or connect an Athena visit');await connect();await click('Check saved visit result');
 await wait(()=>expect(button('Open linked notebook')?.disabled).toBe(false));
 const original=window.fetch;let failed=false;const attempts:string[]=[];
 vi.spyOn(window,'fetch').mockImplementation(async(input,init)=>{
  const action=typeof init?.body==='string'?(JSON.parse(init.body) as {action?:string}).action:undefined;
  if(action)attempts.push(action);
  if(action==='open'&&!failed){failed=true;return new Response(JSON.stringify({detail:'core_connection_unavailable'}),{status:503,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});}
  return original(input,init);
 });
 const opened=vi.spyOn(workspaceApi,'openExisting');await click('Open linked notebook');
 const task=host.querySelector('[aria-label="Find or connect an Athena visit"]')!;
 await wait(()=>expect([...task.querySelectorAll('[role="alert"]')].some(e=>visible(e)&&e.textContent?.includes('The notebook could not be confirmed.'))).toBe(true));
 expect(opened).not.toHaveBeenCalled();await click('Open linked notebook');await wait(()=>expect(opened).toHaveBeenCalledOnce());
 await wait(()=>expect(task.closest('[hidden]')).not.toBeNull());expect(attempts).toEqual(['open','open']);
});

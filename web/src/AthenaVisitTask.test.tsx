import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
const foreground=vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_CORE_CONNECTION_ENABLED','true');vi.stubEnv('VITE_ATHENA_CONNECTION_ENABLED','true');vi.stubEnv('VITE_ATHENA_VISIT_LINK_ENABLED','true');return {resume:()=>{},suspend:()=>{}};});
vi.mock('./native-workspace-foreground',()=>({subscribeNativeWorkspaceForeground:(_identity:unknown,resume:()=>void,suspend:()=>void)=>{foreground.resume=resume;foreground.suspend=suspend;return()=>{};}}));
import {AthenaVisitTask} from './AthenaVisitTask';
import {AccountRecoveryContext,type AccountRecoveryAccess} from './account-recovery';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {athenaRehearsal} from '../ux-acceptance/athena';
import {accountIdentityApi} from './account-identity-api';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import type {AthenaVisitRecoveryRecord} from './athena-visit-link-recovery';
import {coreDigest} from './core-connection-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>'invented-token',nativeSession:{revision:'invented-session',isCurrent:()=>true}};
const account={contract_version:1 as const,box_id:'00000000-0000-4000-8000-000000000011',actor_id:'00000000-0000-4000-8000-000000000012',recovery_scope:'a'.repeat(64)};
let host:HTMLDivElement,root:Root,access:AccountRecoveryAccess,fetcher:ReturnType<typeof vi.fn<typeof fetch>>,open:ReturnType<typeof vi.fn>,denied:ReturnType<typeof vi.fn>;
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>!b.closest('[hidden]')&&b.textContent?.trim()===label);
async function wait(check:()=>void){for(let n=0;n<300;n++){let okay=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();okay=true;}catch{}});if(okay)return;}check();}
async function click(label:string){await wait(()=>expect(button(label)?.disabled,label+' '+host.textContent).toBe(false));await act(async()=>button(label)!.click());}
async function mount(who=identity,opened=true){await act(async()=>root.render(<AccountRecoveryContext.Provider value={access}><AthenaVisitTask identity={who} open={opened} returnLabel="Back to Chief" onReturn={()=>{}} onOpenNotebook={open} onAuthenticationLost={denied}/></AccountRecoveryContext.Provider>));}
async function findVisit(){await click('Check connection status');await click('Check Athena connection');await click('View Athena appointments');await click('Connect or open visit');}
async function prepareLink(){await findVisit();await click('Find Cosmaneura visits');await click('Review this visit');await wait(()=>expect(host.querySelector('input[type="checkbox"]')).not.toBeNull());await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());}
async function savedRecord(){const value=await access.journal.load(accountEditorAddress('athena-visit-link'));expect(value?.kind).toBe('account-editor');if(value?.kind!=='account-editor')throw new Error('Missing recovery');return value.data as AthenaVisitRecoveryRecord;}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');sessionStorage.clear();history.replaceState(null,'','/');HTMLElement.prototype.scrollIntoView=vi.fn();
 const storage=await memoryDraftStorage()({scope:'invented'});access={journal:new DraftJournal(storage),recoveryScope:account.recovery_scope,authorize:vi.fn(async()=>{})};
 vi.spyOn(accountIdentityApi,'read').mockResolvedValue(account);
 const server=await athenaRehearsal('mounted-athena',true);
 fetcher=vi.fn<typeof fetch>(async(input,init)=>{const path=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,location.href).pathname;const response=await server(path,init);if(!response)throw new Error('Unsupported local fixture route');return response;});vi.stubGlobal('fetch',fetcher);
 open=vi.fn(async()=>{});denied=vi.fn();host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();history.replaceState(null,'','/');});
it.each(['link','unlink'] as const)('survives mounted reload after lost %s reply and checks only the exact saved command',async operation=>{
 history.replaceState(null,'',`/?scenario=athena-lost-${operation}`);await mount();await prepareLink();await click('Save visit connection');
 if(operation==='unlink'){await click('Review removing connection');await wait(()=>expect(host.querySelector('input[type="checkbox"]')).not.toBeNull());await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('Remove visit connection');}
 await wait(()=>expect(button('Check saved visit result')).toBeDefined());const record=await savedRecord();expect(record.resolution).toBeNull();
 const before=fetcher.mock.calls.length;await act(async()=>root.unmount());root=createRoot(host);await mount();await wait(()=>expect(button('Check saved visit result')).toBeDefined());
 expect(fetcher).toHaveBeenCalledTimes(before);expect(host.textContent).not.toContain('Jordan Cypress');expect(button('Check connection status')).toBeUndefined();
 await click('Check saved visit result');await wait(()=>expect(host.textContent).toContain(operation==='link'?'Connected to Jordan Cypress':'The visit connection was removed'));
 const commands=fetcher.mock.calls.map(([,init])=>JSON.parse(String(init?.body)));
 expect(commands.filter(c=>c.action===`athena_visit_${operation}`)).toHaveLength(1);
 expect(commands.at(-1)).toMatchObject({action:'athena_visit_status',command_key:record.request.command_key,command_sha256:record.command_sha256});
 expect(commands.at(-1).request_nonce).not.toBe(record.request.request_nonce);expect(JSON.stringify(await savedRecord())).not.toContain('Jordan Cypress');expect(denied).not.toHaveBeenCalled();
});
it('hides all restored patient details until an explicit fresh check and keeps the host when hidden',async()=>{
 await mount();await prepareLink();await click('Save visit connection');await wait(()=>expect(button('Open linked notebook')).toBeDefined());
 await mount(identity,false);expect(button('Open linked notebook')).toBeUndefined();await mount(identity,true);expect(button('Open linked notebook')).toBeDefined();
 await act(async()=>root.unmount());root=createRoot(host);const before=fetcher.mock.calls.length;await mount();await wait(()=>expect(button('Check saved visit result')).toBeDefined());
 expect(host.textContent).not.toContain('Jordan Cypress');expect(fetcher).toHaveBeenCalledTimes(before);await click('Check saved visit result');await click('Open linked notebook');expect(open).toHaveBeenCalledOnce();
});
it('suspends a committed in-flight mutation, then restores metadata on foreground without replay',async()=>{
 let finish!:(response:Response)=>void,entered!:()=>void;const started=new Promise<void>(resolve=>{entered=resolve;});
 const original=fetcher.getMockImplementation()!;fetcher.mockImplementation(async(input,init)=>{const response=await original(input,init);if(JSON.parse(String(init?.body)).action==='athena_visit_link'){entered();return new Promise<Response>(resolve=>{finish=resolve;setTimeout(()=>finish(response),50);});}return response;});
 await mount();await prepareLink();await click('Save visit connection');await started;await act(async()=>foreground.suspend());
 await wait(()=>expect(host.textContent).toContain('Return to the app'));expect(host.textContent).not.toContain('Jordan Cypress');
 await act(async()=>{await new Promise(r=>setTimeout(r,65));foreground.resume();});await wait(()=>expect(button('Check saved visit result')).toBeDefined());
 expect((await savedRecord()).resolution).toBeNull();await click('Check saved visit result');await wait(()=>expect(host.textContent).toContain('Connected to Jordan Cypress'));
 expect(fetcher.mock.calls.filter(([,init])=>JSON.parse(String(init?.body)).action==='athena_visit_link')).toHaveLength(1);
});
it('does not show a saved source for a replacement account or issue a provider read',async()=>{
 await mount();await prepareLink();await click('Save visit connection');const calls=fetcher.mock.calls.length;
 vi.mocked(accountIdentityApi.read).mockResolvedValue({...account,actor_id:crypto.randomUUID(),recovery_scope:'b'.repeat(64)});
 await mount({...identity,getToken:async()=>'another-invented-token'});await wait(()=>expect(denied).toHaveBeenCalled());
 expect(host.textContent).not.toContain('Jordan Cypress');expect(fetcher).toHaveBeenCalledTimes(calls);expect(button('Open linked notebook')).toBeUndefined();
});
it.each(['patient','removal'] as const)('keeps mounted reload recovery pending for a different %s target',async fault=>{
 history.replaceState(null,'',`/?scenario=athena-lost-${fault==='patient'?'link':'unlink'}`);await mount();await prepareLink();await click('Save visit connection');
 if(fault==='removal'){await click('Review removing connection');await wait(()=>expect(host.querySelector('input[type="checkbox"]')).not.toBeNull());await act(async()=>host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());await click('Remove visit connection');}
 await wait(()=>expect(button('Check saved visit result')).toBeDefined());const record=await savedRecord();await act(async()=>root.unmount());root=createRoot(host);await mount();
 const original=fetcher.getMockImplementation()!;fetcher.mockImplementationOnce(async(input,init)=>{const response=await original(input,init),value=await response.json(),d=value.athena_visit_link;
  if(fault==='patient'){const e=d.encounter;e.patient.patient_ref='patient_00000000000000000000000002';e.appointment.patient_ref=e.patient.patient_ref;const {source_sha256:_old,...body}=e;e.source_sha256=await coreDigest(body);}
  else d.link_ref='athena_visit_link_00000000000000000000000002';
  return new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});});
 await click('Check saved visit result');await wait(()=>expect(host.textContent).toContain('could not be verified'));expect(button('Open linked notebook')).toBeUndefined();expect(await savedRecord()).toEqual(record);
 await click('Check saved visit result');await wait(()=>expect((host.textContent??'').includes('Connected to Jordan')||(host.textContent??'').includes('was removed')).toBe(true));
 const commands=fetcher.mock.calls.map(([,init])=>JSON.parse(String(init?.body))).filter(c=>c.action==='athena_visit_status');expect(commands).toHaveLength(2);expect(commands[0].command_key).toBe(commands[1].command_key);expect(commands[0].command_sha256).toBe(commands[1].command_sha256);
});

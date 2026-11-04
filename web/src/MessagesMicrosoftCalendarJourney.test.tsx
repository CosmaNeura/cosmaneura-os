import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {waitMessagesJourney as wait,MESSAGES_JOURNEY_TEST_TIMEOUT_MS} from './messages-journey-wait';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED','VITE_MICROSOFT_MESSAGE_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {openDraftStore} from './draft-store';
import {PRESENTATION_KEY} from './session/presentation';
import {workspaceApi,type Workspace} from './workspace-api';
import {teamCanonical} from './team-setup-request';
import {microsoftCalendarEventHash,microsoftCalendarSourceContent,microsoftCalendarSourceHash,microsoftCalendarReviewHash,validMicrosoftCalendarReviewRequest,type MicrosoftCalendarReceipt,type MicrosoftCalendarReviewRequest} from './microsoft-calendar-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.setConfig({testTimeout:MESSAGES_JOURNEY_TEST_TIMEOUT_MS});
let root:Root,host:HTMLDivElement,idb:IDBFactory,receipt:MicrosoftCalendarReceipt,saved:Workspace|null,unavailable:boolean;
const calls:{action:string;body:Record<string,unknown>}[]=[];
const storage=({scope}:{scope:string})=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
const task=()=>[...host.querySelectorAll<HTMLElement>('.ehr-read-task[aria-label="Review Outlook Calendar"]')].find(visible);
async function click(name:string){let sent=false;await wait(()=>{if(sent)return;const target=button(name);expect(target,name).toBeTruthy();expect(target!.disabled,name).toBe(false);sent=true;target!.focus({preventScroll:true});target!.click();});}
async function type(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function openChat(){const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(b=>visible(b)&&b.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()?.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(question()?.disabled).toBe(false));}
async function openTask(){await click('Details');await click('Choose notes or sources');await click('Review Outlook Calendar');await wait(()=>expect(task()).toBeDefined());await wait(()=>expect(['Check calendar access','Restore saved calendar work'].some(name=>button(name)?.disabled===false),task()?.textContent).toBe(true));}
const digest=async(value:string)=>[...new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(n=>n.toString(16).padStart(2,'0')).join('');
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();saved=null;unavailable=false;calls.length=0;localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','?scenario=outlook-happy#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 const fixtureFetch=window.fetch,fixtureRead=workspaceApi.read;
 workspaceApi.read=async(...args)=>saved&&args[1]===saved.id?structuredClone(saved):fixtureRead(...args);
 const now=new Date(),end=new Date(now.getTime()+7*86400000),observation={kind:'calendar' as const,account:{label:'Invented Outlook clinic',email:'doctor@example.invalid'},items:[
  {id:'AAMk+/selected==',subject:'Invented exact follow-up event',starts_at:new Date(now.getTime()+3600000).toISOString(),ends_at:new Date(now.getTime()+7200000).toISOString(),all_day:false,cancelled:false},
  {id:'AAMk+/unrelated==',subject:'Invented unrelated planning',starts_at:new Date(now.getTime()+10800000).toISOString(),ends_at:new Date(now.getTime()+14400000).toISOString(),all_day:true,cancelled:true}],more:true,observed_at:now.toISOString(),window:{starts_at:now.toISOString(),ends_at:end.toISOString()}};
 receipt={contract_version:1,observation_id:crypto.randomUUID(),observation_key:crypto.randomUUID(),source_sha256:'a'.repeat(64),payload_sha256:await digest(teamCanonical(observation)),observation};
 // Temporary test transport handles only the owned calendar routes and saved
 // workspace projection. All other calls stay in the existing local fixture.
 // There is no external network or provider fallback.
 window.fetch=async(input,init)=>{
  const url=typeof input==='string'?input:input instanceof URL?input.href:input.url,path=new URL(url,window.location.href).pathname;
  const review=/^\/workspaces\/([a-f0-9-]{36})\/microsoft-calendar\/review$/.exec(path);
  if(path==='/connections/microsoft/calendar-summaries'||review){
   if(unavailable)return response({detail:'microsoft_calendar_unavailable'},404);
   const headers=new Headers(init?.headers),body=JSON.parse(String(init?.body));expect(init?.method).toBe('POST');expect(headers.get('X-Cosmas-Microsoft-Calendar')).toBe('1');calls.push({action:review?'review':body.action,body});
   if(body.action==='status')return response({contract_version:1,state:'connected',calendar_read:true,account:observation.account});
   if(body.action==='observe'){receipt={...receipt,observation_key:body.idempotency_key};return response(receipt);}
   if(body.action==='inspect')return response(receipt);
   if(review){
    expect(validMicrosoftCalendarReviewRequest(body)).toBe(true);const b=body as MicrosoftCalendarReviewRequest,event=receipt.observation.items.find(e=>e.id===b.event_id)!;
    expect(b.observation_id).toBe(receipt.observation_id);expect(b.observation_sha256).toBe(receipt.source_sha256);expect(b.event_sha256).toBe(await microsoftCalendarEventHash(event));
    const before=saved??await fixtureRead(identity,review[1]);
    expect(before.id).toBe(review[1]);expect(before.appointment_id).not.toBeNull();expect(before.revision).toBe(b.expected_revision);
    const content=microsoftCalendarSourceContent(observation,event),entry_id=crypto.randomUUID(),revision=before.revision+1;
    saved={...before,revision,model_observed_at:new Date().toISOString(),entries:[...before.entries,{id:entry_id,revision,kind:'microsoft_calendar',content,source_label:'Outlook calendar: '+event.subject,microsoft_calendar_source_state:'current',created_at:new Date().toISOString(),origin:'authenticated_human',ticket:null}]};
    return response({entry_id,entry_revision:revision,request_sha256:await microsoftCalendarReviewHash(review[1],b),source_withheld:false,workspace:saved,source:{entry_id,source_sha256:await microsoftCalendarSourceHash(receipt,event),content_sha256:await digest(content)}});
   }
   throw new Error('Unexpected invented calendar command');
  }
  if(saved&&path===`/workspaces/${saved.id}`&&(!init?.method||init.method==='GET'))return response(saved);
  return fixtureFetch(input,init);
 };
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('chooses one Outlook event, reviews and saves it explicitly, then prepares Chief instructions while retaining the unsent question',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await openChat();await type('Keep my unsent question about this invented visit.');await openTask();expect(calls).toHaveLength(0);
 await click('Check calendar access');expect(task()?.closest('[data-editor-task]')?.getAttribute('data-editor-task')).toBe('microsoft');expect(task()?.closest('.settings-hub')?.querySelector('nav[aria-label="Settings navigation"]')?.hasAttribute('hidden')).toBe(true);await click('Load next 7 days');await wait(()=>expect(task()?.querySelector<HTMLButtonElement>('[data-calendar-event="AAMk+/selected=="]')?.disabled).toBe(false));await act(async()=>task()!.querySelector<HTMLButtonElement>('[data-calendar-event="AAMk+/selected=="]')!.click());
 await wait(()=>expect(button('Use current visit')?.disabled).toBe(false));const exact=task()!.querySelector('pre')!.textContent!;expect(exact).toContain('Invented exact follow-up event');expect(exact).not.toContain('Invented unrelated planning');expect(calls.some(row=>row.action==='review')).toBe(false);
 await click('Use current visit');await wait(()=>expect(task()?.querySelectorAll('input[type="checkbox"]')).toHaveLength(3));expect(button('Save calendar summary to visit')?.disabled).toBe(true);
 for(const input of task()!.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))await act(async()=>input.click());await click('Save calendar summary to visit');await wait(()=>expect(button('Ask Chief about this calendar summary')?.disabled,task()?.textContent+' Calls: '+calls.map(row=>row.action).join(',')+' saved:'+Boolean(saved)).toBe(false));
 expect(calls.filter(row=>row.action==='review')).toHaveLength(1);expect(calls.find(row=>row.action==='review')!.body).toMatchObject({event_id:'AAMk+/selected==',reviewed_visit:true,reviewed_exact_summary:true,reviewed_untrusted_source:true});expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
 await click('Ask Chief about this calendar summary');await wait(()=>expect(question()?.disabled).toBe(false));expect(question().value).toContain('Keep my unsent question');expect(question().value).toContain('Review the human-selected calendar summary');expect(ask).not.toHaveBeenCalled();
});
it('fails closed on an older/unavailable service and retains the conversation draft without a load or save',async()=>{
 unavailable=true;await openChat();await type('Keep my draft when calendar is unavailable.');await openTask();await click('Check calendar access');await wait(()=>expect(task()?.textContent).toContain('Calendar work is unavailable from the practice service'));
 expect(task()?.querySelector('pre')).toBeNull();expect(button('Load next 7 days')?.disabled).toBe(true);expect(calls).toHaveLength(0);await click('‹ Back to Chief of Staff');expect(question().value).toBe('Keep my draft when calendar is unavailable.');
});

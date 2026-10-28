import {act,type ReactNode} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED','true');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {workspaceApi,type Workspace} from './workspace-api';
import {teamFixture,teamUuid as uuid} from './team-setup-test-fixture';
import {memoryDraftStorage} from './draft-test-fixture';
import {settingsNavigation} from './settings-test-navigation';
import {readConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary} from './connection-summary';
import {readinessFixture} from './connection-readiness-fixture';
import type {GoogleCalendarMountProps} from './GoogleCalendarMount';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./draft-store',async original=>({...await original<typeof import('./draft-store')>(),privateDraftScope:async(s:string)=>s}));
vi.mock('./team-setup-api',async()=>{const {WorkspaceApiError}=await import('./workspace-api');return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404))}};});
vi.mock('./connection-catalog-api',async original=>({...await original<typeof import('./connection-catalog-api')>(),readConnectionCatalog:vi.fn()}));
vi.mock('./connection-summary',async original=>({...await original<typeof import('./connection-summary')>(),readConnectionSummary:vi.fn()}));
vi.mock('./GoogleConnectionPanel',()=>({GoogleConnectionPanel:({onOpenCalendarWork,calendarWork}: {onOpenCalendarWork:()=>void;calendarWork?: (controls:unknown)=>ReactNode})=><section><button onClick={onOpenCalendarWork}>📅 Work with calendar</button>{calendarWork?.({requestCalendarAccess:()=>{},calendarAccessBusy:false})}</section>}));
let mount:GoogleCalendarMountProps;
vi.mock('./GoogleCalendarMount',()=>({GoogleCalendarMount:(props:GoogleCalendarMountProps)=>{mount=props;return <section aria-label="Mounted calendar work">{props.workspace?.label??'Choose a visit for calendar'}</section>;}}));
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented'},team=teamFixture();team.capture={enabled:false};team.scheduling={enabled:false};
let root:Root,host:HTMLDivElement,current:Workspace&{appointment_id:string};
const time='2026-10-02T14:00:00Z';
async function wait(check:()=>void){for(let n=0;n<100;n++){let passed=false;await act(async()=>{await new Promise(r=>setTimeout(r,3));try{check();passed=true;}catch{}});if(passed)return;}check();}
async function click(label:string){await wait(()=>expect([...host.querySelectorAll('button')].some(b=>!b.closest('[hidden]')&&b.textContent===label&&!b.disabled)).toBe(true));await act(async()=>[...host.querySelectorAll('button')].find(b=>!b.closest('[hidden]')&&b.textContent===label)!.click());}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
 current={id:uuid(71),appointment_id:uuid(72),label:'Invented Shawn visit',revision:2,work_candidates:[],entries:[{id:uuid(73),revision:2,kind:'scratchpad',content:'Saved encounter note',source_label:null,origin:'human',ticket:null,created_at:time}]};
 vi.spyOn(workspaceApi,'team').mockImplementation(async()=>structuredClone(team));vi.spyOn(workspaceApi,'open').mockImplementation(async()=>({identity,workspace:structuredClone(current),team:structuredClone(team)}));
 vi.spyOn(workspaceApi,'read').mockImplementation(async()=>structuredClone(current));vi.spyOn(workspaceApi,'catalog').mockResolvedValue([{appointment_id:current.appointment_id,workspace_id:current.id,label:current.label}]);vi.spyOn(workspaceApi,'ask');vi.spyOn(workspaceApi,'append');
 vi.mocked(readConnectionCatalog).mockResolvedValue({...readinessFixture(),core:false,google:true,microsoft:false,scheduling:false,messaging:false,payments:false,portals:false});
 vi.mocked(readConnectionSummary).mockResolvedValue({label:'Connected',reason:'Invented Google account',action:'Open email',tone:'ready'});
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
 await click('Visits and notes');await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('opens operational calendar from product settings and prepares Chief without replacing unfinished notes or sending',async()=>{
 const setValue=async(id:string,value:string)=>{await act(async()=>{const field=host.querySelector<HTMLTextAreaElement>(id)!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});};
 await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.querySelector('strong')?.textContent==='chief')!.click());
 await setValue('#team-notebook','Unfinished provider notes');await setValue('#team-question','Existing provider request');
 const nav=settingsNavigation(host);await nav.click('Team settings');await nav.click('Connections');await nav.click('Google email & calendar');await click('📅 Work with calendar');
 expect(host.querySelector('[aria-label="Mounted calendar work"]')?.closest('[hidden]')).toBeNull();expect(mount.workspace?.id).toBe(current.id);
 const originalEmail={id:uuid(79),revision:2,kind:'google_message' as const,content:'Prior reviewed Gmail source',source_label:'Google message: prior',origin:'human',ticket:null,created_at:time,google_source_state:'current' as const};
 current={...current,entries:[...current.entries,originalEmail]};
 const content='Google calendar summary (frozen observation)\nEvent: Invented follow-up\nThis observed summary does not establish current availability or a booking.';
 const sha=[...new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(content)))].map(n=>n.toString(16).padStart(2,'0')).join('');
 current={...current,revision:3,entries:[...current.entries,{id:uuid(74),revision:3,kind:'google_calendar',content,source_label:'Google calendar: Invented referral',origin:'human',ticket:null,created_at:time,calendar_source_state:'current'}]};
 await act(async()=>mount.onSaved(structuredClone(current)));
 expect(mount.currentSources).toEqual([{entry_id:uuid(74),state:'current'}]);
 await act(async()=>mount.onAskChief!({workspace_id:current.id,entry_id:uuid(74),entry_revision:3,source_sha256:'a'.repeat(64),content_sha256:sha,request_sha256:'b'.repeat(64),source_withheld:false}));
 await wait(()=>expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toContain(uuid(74)));
 expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.value).toContain('Existing provider request');
 expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.value).not.toContain('Please arrange follow-up.');
 expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe('Unfinished provider notes');
 expect(current.entries.find(e=>e.id===uuid(79))?.content).toBe('Prior reviewed Gmail source');
 expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
});

it('offers Chief starters for a current reviewed calendar without copying it into the notebook',async()=>{
 const saved=current.entries;
 current={...current,entries:[{id:uuid(74),revision:2,kind:'google_calendar',content:'Invented calendar source',source_label:'Google calendar: Invented request',origin:'human',ticket:null,created_at:time,calendar_source_state:'current'}]};
 await act(async()=>root.unmount());root=createRoot(host);
 await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
 await click('Visits and notes');await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
 await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.querySelector('strong')?.textContent==='chief')!.click());
 await wait(()=>expect([...host.querySelectorAll('button')].find(b=>b.textContent==='Prepare team drafts')?.disabled).toBe(false));
 expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.value).toBe('');
 current={...current,entries:current.entries.map(e=>({...e,content:'',calendar_source_state:'unavailable' as const}))};
 await act(async()=>root.unmount());root=createRoot(host);
 await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
 await click('Visits and notes');await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
 await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.querySelector('strong')?.textContent==='chief')!.click());
 await wait(()=>expect([...host.querySelectorAll('button')].find(b=>b.textContent==='Prepare team drafts')?.disabled).toBe(true));
 expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
 current={...current,entries:saved};
});

it('rechecks a revoked calendar source before preparing Chief and immediately updates the unavailable projection',async()=>{
 const nav=settingsNavigation(host);await nav.click('Team settings');await nav.click('Connections');await nav.click('Google email & calendar');await click('📅 Work with calendar');
 current={...current,revision:3,entries:[...current.entries,{id:uuid(74),revision:3,kind:'google_calendar',content:'',source_label:'Unavailable calendar source',origin:'human',ticket:null,created_at:time,calendar_source_state:'unavailable'}]};
 await act(async()=>mount.onAskChief!({workspace_id:current.id,entry_id:uuid(74),entry_revision:3,source_sha256:'a'.repeat(64),content_sha256:'b'.repeat(64),request_sha256:'c'.repeat(64),source_withheld:false}));
 await wait(()=>expect(mount.currentSources).toEqual([{entry_id:uuid(74),state:'unavailable'}]));expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
 expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).not.toContain('human-selected calendar summary');
});

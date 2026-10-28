import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const [key,value] of Object.entries({VITE_COSMAS_ENV:'synth_os',VITE_WORKSPACE_ENABLED:'true',VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED:'true',VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED:'true',VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED:'true'}))vi.stubEnv(key,value);});
import {googleConnectionRequest} from '../src/google-connection-api';
import {googleCalendarApi,googleCalendarEventHash,type GoogleCalendarReceipt} from '../src/google-calendar-api';
import {gmailRehearsal} from './gmail';
import {googleCalendarRehearsal,type CalendarRehearsalStats} from './google-calendar';
import type {Workspace} from '../src/workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`,scope={box_id:uuid(1),actor_id:uuid(2)},identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-fixture-token'};
let workspace:Workspace,mail:ReturnType<typeof gmailRehearsal>;
const stats=()=>(window as unknown as {calendarRehearsalStats:CalendarRehearsalStats}).calendarRehearsalStats;
const controls=()=>(window as unknown as {gmailRehearsalControls:{changeGrant():void;disconnect():void}}).gmailRehearsalControls;
function open(calendarEnabled=true,calendarScope=scope){
 mail=gmailRehearsal(()=>workspace,value=>{workspace=value;},'invented-shared-google',false,scope,calendarEnabled);
 const calendar=googleCalendarRehearsal(()=>workspace,value=>{workspace=value;},'invented-shared-google',false,calendarScope,mail.calendarConnection);
 vi.stubGlobal('fetch',async(input:string|URL|Request,init?:RequestInit)=>{const path=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,location.href).pathname;const result=await calendar(path,init)??await mail(path,init);if(!result)throw Error('No external fallback');return result;});
}
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);sessionStorage.clear();history.replaceState(null,'','/');workspace={id:uuid(71),appointment_id:uuid(72),label:'Invented visit',revision:5,entries:[],work_candidates:[],follow_ups:[],model_contract_version:1,model_observed_at:new Date().toISOString()};open();});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
const observe=()=>googleCalendarApi.observe(identity,{action:'observe',idempotency_key:crypto.randomUUID()});
async function save(receipt:GoogleCalendarReceipt){const event=receipt.observation.items[0];const command={expected_revision:workspace.revision,idempotency_key:crypto.randomUUID(),observation_id:receipt.observation_id,observation_sha256:receipt.source_sha256,event_id:event.id,event_sha256:await googleCalendarEventHash(event),reviewed_visit:true as const,reviewed_exact_summary:true as const,reviewed_untrusted_source:true as const};return {command,result:await googleCalendarApi.review(identity,workspace.id,command,receipt)};}
it('uses one account and Calendar capability on the no-scenario route through the real API validators',async()=>{
 const connection=await googleConnectionRequest(identity,'status'),calendar=await googleCalendarApi.status(identity);expect(connection).toMatchObject({state:'connected',capabilities:{calendar:true}});expect(calendar).toMatchObject({state:'connected',calendar_read:true,account:{email:'owner@example.invalid'}});expect('account'in connection&&connection.account).toEqual(calendar.account);expect(stats().observes).toBe(0);
 const receipt=await observe();expect(receipt.observation.account).toEqual(calendar.account);await save(receipt);expect(workspace.entries[0]).toMatchObject({kind:'google_calendar',calendar_source_state:'current'});expect(stats()).toMatchObject({observes:1,reviews:1,externalCalls:0});
});
it.each(['disconnect','changeGrant'] as const)('withdraws saved Calendar material immediately on shared %s and rejects every old request without another read',async action=>{
 const receipt=await observe(),saved=await save(receipt);controls()[action]();expect(workspace.entries[0]).toMatchObject({id:saved.result.entry_id,content:'',source_label:'Unavailable calendar source',calendar_source_state:'unavailable'});
 await expect(googleCalendarApi.inspect(identity,receipt)).rejects.toMatchObject({code:action==='disconnect'?'google_calendar_grant_unavailable':'google_calendar_grant_changed'});await expect(googleCalendarApi.resolve(identity,receipt.observation_key)).rejects.toMatchObject({status:409});await expect(googleCalendarApi.review(identity,workspace.id,saved.command,receipt)).rejects.toMatchObject({status:409});expect(stats()).toMatchObject({observes:1,reviews:1});
 if(action==='disconnect')expect(await googleCalendarApi.status(identity)).toMatchObject({state:'sign_in_required',calendar_read:false,account:null});
});
it('requires the shared Calendar capability and refuses a foreign actor snapshot',async()=>{
 open(false);expect(await googleCalendarApi.status(identity)).toMatchObject({calendar_read:false});await expect(observe()).rejects.toMatchObject({code:'google_calendar_consent_required'});expect(stats().observes).toBe(0);
 open(true,{...scope,actor_id:uuid(3)});expect(await googleCalendarApi.status(identity)).toMatchObject({state:'sign_in_required',account:null});await expect(observe()).rejects.toMatchObject({code:'google_calendar_grant_unavailable'});expect(stats().observes).toBe(0);
});
it('exposes a detached connection snapshot and preserves named Calendar scenario isolation',async()=>{
 const snapshot=mail.calendarConnection();snapshot.scope.actor_id=uuid(999);snapshot.account.email='changed@example.invalid';expect(mail.calendarConnection()).toMatchObject({scope,account:{email:'owner@example.invalid'}});
 history.replaceState(null,'','/?scenario=google-calendar-happy');open(false);controls().disconnect();expect(await googleCalendarApi.status(identity)).toMatchObject({state:'connected',calendar_read:true,account:{email:'calendar@example.invalid'}});expect(stats().observes).toBe(0);
});

it('refuses a request if the shared grant changes while admission hashing waits, without rebinding its key',async()=>{
 const digest=crypto.subtle.digest.bind(crypto.subtle);let release!:()=>void;vi.spyOn(crypto.subtle,'digest').mockImplementationOnce((algorithm,data)=>new Promise(resolve=>{release=()=>{void digest(algorithm,data).then(resolve);};}));
 const pending=observe();void pending.catch(()=>{});await vi.waitFor(()=>expect(release).toBeTypeOf('function'));controls().changeGrant();release();await expect(pending).rejects.toMatchObject({code:'google_calendar_grant_changed'});expect(stats().observes).toBe(0);expect(workspace.entries).toEqual([]);expect(JSON.parse(sessionStorage.getItem('invented-shared-google:google-calendar')!).rows).toEqual([]);
});
it('checks the captured lease again before publishing a reviewed workspace or ledger row',async()=>{
 const receipt=await observe(),digest=crypto.subtle.digest.bind(crypto.subtle);let release!:()=>void,matching=0;vi.spyOn(crypto.subtle,'digest').mockImplementation((algorithm,data)=>{
  const text=new TextDecoder().decode(data);if(text.includes('"workspace_id"')&&text.includes(workspace.id)&&++matching===2)return new Promise(resolve=>{release=()=>{void digest(algorithm,data).then(resolve);};});return digest(algorithm,data);
 });
 const pending=save(receipt);void pending.catch(()=>{});await vi.waitFor(()=>expect(release).toBeTypeOf('function'));expect(workspace.entries).toEqual([]);controls().disconnect();release();await expect(pending).rejects.toMatchObject({code:'google_calendar_grant_unavailable'});expect(workspace.entries).toEqual([]);expect(stats().reviews).toBe(0);expect(JSON.parse(sessionStorage.getItem('invented-shared-google:google-calendar')!).rows).toHaveLength(1);
});

import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED','true');});
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {SchedulingPatientPanel} from './SchedulingPatientPanel';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal,editorAddress} from './draft-journal';
import {DraftStoreError,openDraftStore,type DraftValue} from './draft-store';
import {type Workspace,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {schedulingPatientDigest,schedulingPatientRequestHash,validateSchedulingPatientReceipt,validSchedulingPatientCommand,
 type SchedulingPatientCommand,type SchedulingPatientChoice,type SchedulingPatientReceipt} from './scheduling-patient-api';
import {validateSchedulingPatientRecovery,type SchedulingPatientRecovery} from './scheduling-patient-recovery';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-patient-token'},address=editorAddress(uuid(1),'scheduling-patient');
let root:Root,host:HTMLDivElement,idb:IDBFactory,journal:DraftJournal,access:EditorRecoveryAccess|null,workspace:Workspace,scope:string,failWrites:number,requests:SchedulingPatientCommand[],afterWrite:((value:DraftValue|null)=>Promise<void>)|null;
const linked=vi.fn(),denied=vi.fn(),busyChanged=vi.fn();
const json=(v:unknown)=>new Response(JSON.stringify(v),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
async function choice(n=1):Promise<SchedulingPatientChoice>{const fields={choice_ref:uuid(10+n),display_name:n===1?'Shawn Café':'Shawn Other',birth_date:n===1?null:'1980-04-12',subject_revision:1};return {...fields,identity_sha256:await schedulingPatientDigest('cosmas-scheduling-patient-identity.v1',fields)};}
async function preview(command:SchedulingPatientCommand):Promise<SchedulingPatientReceipt>{const checkedAt=Date.now();return {contract_version:1,kind:'preview',request_id:uuid(30),request_key:command.idempotency_key,
 request_sha256:await schedulingPatientRequestHash(workspace.id,command),status:'saved',source_withheld:false,source_sha256:'a'.repeat(64),preview:{checked_at:new Date(checkedAt).toISOString(),expires_at:new Date(checkedAt+300000).toISOString(),choices:[await choice(),await choice(2)],more:false},mapping:null};}
async function confirmed(command:SchedulingPatientCommand):Promise<SchedulingPatientReceipt>{if(command.action!=='confirm')throw new Error('Wrong command');return {contract_version:1,kind:'confirm',request_id:uuid(31),request_key:command.idempotency_key,
 request_sha256:await schedulingPatientRequestHash(workspace.id,command),status:'saved',source_withheld:false,source_sha256:'b'.repeat(64),preview:null,
 mapping:{mapping_id:uuid(32),mapping_sha256:'c'.repeat(64),identity_sha256:command.identity_sha256,subject_revision:1}};}
let receipts:Map<string,SchedulingPatientReceipt>,lost:'none'|'preview_before'|'preview_after'|'confirm_after';
async function wire(_url:string,init:RequestInit){const body=JSON.parse(String(init.body));
 if(body.action==='status')return json({contract_version:1,state:'link_required',mapping_id:null});
 if(body.action==='resolve')return json(receipts.get(body.idempotency_key)??{contract_version:1,kind:body.kind,request_id:null,request_key:body.idempotency_key,request_sha256:null,status:'not_found',source_withheld:false,source_sha256:null,preview:null,mapping:null});
 if(body.action==='inspect'){const r=[...receipts.values()].find(r=>r.request_id===body.request_id);return json(r);}
 requests.push(body);expect(await journal.load(address)).toMatchObject({pending:body.idempotency_key,data:{pending:body}});
 if(lost==='preview_before'&&body.action==='preview'){lost='none';throw new TypeError('lost before server reservation');}
 const result=body.action==='preview'?await preview(body):await confirmed(body);receipts.set(body.idempotency_key,result);
 if(lost==='preview_after'&&body.action==='preview'||lost==='confirm_after'&&body.action==='confirm'){lost='none';throw new TypeError('lost after server save');}
 return json(result);
}
async function store(){const storage=await openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});return {read:storage.read.bind(storage),close:storage.close.bind(storage),write:async(id:string,expected:string|null,value:DraftValue|null)=>{
 if(id===address&&failWrites){failWrites--;throw new DraftStoreError('unavailable');}const saved=await storage.write(id,expected,value);if(id===address&&afterWrite)await afterWrite(value);return saved;}};}
async function newJournal(){journal=new DraftJournal(await store());access={journal,workspaceId:workspace.id,authorize:vi.fn(async()=>workspace),denied};}
function Harness({enabled=true,auth=identity,observationStamp}:{enabled?:boolean;auth?:AuthenticatedWorkspaceIdentity;observationStamp?:number}){const [w]=useState(workspace);return <EditorRecoveryContext.Provider value={access}><SchedulingPatientPanel identity={auth} workspace={w} enabled={enabled} locked={false} observationStamp={observationStamp} onLinked={linked} onAccessLost={denied} onBusyChange={busyChanged}/></EditorRecoveryContext.Provider>;}
const button=(name:string)=>{const b=[...host.querySelectorAll('button')].find(b=>b.textContent===name);expect(b,name).toBeTruthy();return b!;};
async function wait(check:()=>void|Promise<void>){for(let i=0;i<200;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,3));try{await check();done=true;}catch{}});if(done)return;}await check();}
async function click(name:string){await wait(()=>expect(button(name).disabled).toBe(false));await act(async()=>button(name).click());}
async function fill(label:string,text:string){const field=host.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;expect(field.disabled).toBe(false);await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(field,text);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function mount(){await act(async()=>root.render(<Harness/>));await wait(()=>expect(button('Find patient').disabled).toBe(true));}
async function reopen(){await act(async()=>root.unmount());journal.close();await newJournal();root=createRoot(host);await mount();}
async function search(){await fill('Patient name','Shawn');await click('Find patient');try{await wait(()=>expect(host.querySelector('[aria-label="Patient matches"]')).toBeTruthy());}catch(e){throw new Error(String(e)+'; '+host.textContent+'; requests='+requests.length);}}
async function lostRequest(kind:'preview'|'confirm',committed:boolean){await wait(()=>{
 const command=[...requests].reverse().find(command=>command.action===kind);expect(command).toBeTruthy();expect(receipts.has(command!.idempotency_key)).toBe(committed);
 expect(host.querySelector('[aria-label="Scheduling patient setup"]')?.getAttribute('aria-busy')).toBe('false');expect(host.textContent).toContain('Patient setup could not be confirmed');
});}
async function select(){await click('Shawn Café · DOB not supplied');const checks=host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');expect(checks).toHaveLength(2);for(const input of checks)await act(async()=>input.click());}
beforeEach(async()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');
 idb=new IDBFactory();scope='a'.repeat(64);failWrites=0;afterWrite=null;requests=[];receipts=new Map();lost='none';workspace={id:uuid(1),appointment_id:uuid(2),label:'Invented Shawn visit',revision:3,entries:[],work_candidates:[]};await newJournal();linked.mockClear();denied.mockClear();busyChanged.mockClear();vi.stubGlobal('fetch',vi.fn(wire));host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());journal.close();host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
it.each(['physician','nurse_practitioner','physician_assistant'])('%s explicitly searches without DOB, chooses, checks exact identity and saves mapping without a booking',async()=>{
 await mount();expect(fetch).not.toHaveBeenCalled();await search();expect(requests[0]).toMatchObject({search:{kind:'search',query:'Shawn',birth_date:null}});
 expect([...host.querySelectorAll('[aria-label="Patient matches"] button')].every(b=>b.getAttribute('aria-pressed')==='false')).toBe(true);expect(host.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
 await click('Shawn Café · DOB not supplied');expect(button('Save patient connection').disabled).toBe(true);for(const input of host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))await act(async()=>input.click());
 await click('Save patient connection');await wait(()=>expect(host.textContent).toContain('Patient ready'));expect(requests).toHaveLength(2);expect(linked).toHaveBeenCalledOnce();expect(host.textContent).toContain('no appointment was booked');
 expect(requests[1]).toMatchObject({reviewed_same_patient:true,reviewed_exact_identity:true,choice_ref:uuid(11)});expect(Object.keys(requests[1])).not.toContain('patient_id');expect(workspace.entries).toEqual([]);
 await wait(()=>expect(busyChanged).toHaveBeenLastCalledWith(false));
});
it('preserves unsubmitted name/optional DOB through actual encrypted reopen without lookup or autoselection',async()=>{
 await mount();await fill('Patient name','Shawn Café');await fill('Date of birth (optional)','1980-04-12');await wait(async()=>expect(await journal.load(address)).toMatchObject({data:{query:'Shawn Café',birth_date:'1980-04-12'}}));
 await reopen();await click('Restore scheduling patient draft');await wait(()=>expect(host.querySelector<HTMLInputElement>('[aria-label="Patient name"]')!.value).toBe('Shawn Café'));
 expect(fetch).not.toHaveBeenCalled();expect(host.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);expect(host.querySelector('[aria-label="Patient matches"]')).toBeNull();
});
it.each(['preview_before','preview_after'] as const)('reopens %s loss, resolves original key and never automatically repeats a receiver request',async failure=>{
 lost=failure;await mount();await fill('Patient name','Shawn');await click('Find patient');await lostRequest('preview',failure==='preview_after');
 const original=requests[0],calls=vi.mocked(fetch).mock.calls.length;await reopen();await click('Restore scheduling patient draft');await wait(()=>expect(button('Check saved setup result').disabled).toBe(false));expect(vi.mocked(fetch).mock.calls.length).toBe(calls);
 await click('Check saved setup result');if(failure==='preview_after'){await wait(()=>expect(host.querySelector('[aria-label="Patient matches"]')).toBeTruthy());expect(requests).toHaveLength(1);}
 else{await wait(()=>expect(button('Retry same setup request').disabled).toBe(false));expect(requests).toHaveLength(1);await click('Retry same setup request');await wait(()=>expect(requests).toHaveLength(2));expect(requests[1]).toEqual(original);}
});
it('prevents receiver lookup if protected command storage fails',async()=>{
 await mount();await fill('Patient name','Shawn');await wait(async()=>expect(await journal.load(address)).not.toBeNull());failWrites=1;await click('Find patient');await wait(()=>expect(host.textContent).toContain('Private storage could not save'));
 expect(requests).toHaveLength(0);expect(fetch).not.toHaveBeenCalled();expect(host.textContent).not.toContain('Patient ready');
});
it('confirms a lost mapping save by exact original request commitment after encrypted reopen',async()=>{
 await mount();await search();await select();lost='confirm_after';await click('Save patient connection');await lostRequest('confirm',true);
 const original=requests[1];await reopen();await click('Restore scheduling patient draft');await wait(()=>expect(button('Check saved setup result').disabled).toBe(false));expect(linked).not.toHaveBeenCalled();
 await click('Check saved setup result');await wait(()=>expect(host.textContent).toContain('Patient ready'));expect(requests).toHaveLength(2);expect(linked).toHaveBeenCalledOnce();
 const local=await journal.load(address);expect(local).toMatchObject({pending:null,data:{saved:{request_key:original.idempotency_key},pending:null}});
});
it('withholds revoked receipt labels and does not claim mapping readiness from masked history',async()=>{
 await mount();await search();await select();lost='confirm_after';await click('Save patient connection');await lostRequest('confirm',true);
 const old=receipts.get(requests[1].idempotency_key)!;receipts.set(old.request_key,{...old,source_withheld:true,mapping:null,preview:null});await reopen();await click('Restore scheduling patient draft');
 await click('Check saved setup result');await wait(()=>expect(host.textContent).toContain('exact saved setup is confirmed'));expect(host.textContent).not.toContain('Shawn Café');expect(host.textContent).not.toContain('Patient ready');expect(linked).not.toHaveBeenCalled();
});
it('retains an unresolved server reservation without showing a provider retry button',async()=>{
 await mount();lost='preview_after';await fill('Patient name','Shawn');await click('Find patient');await lostRequest('preview',true);const old=receipts.get(requests[0].idempotency_key)!;
 receipts.set(old.request_key,{...old,status:'unconfirmed',source_sha256:null,preview:null,mapping:null});await click('Check saved setup result');await wait(()=>expect(host.textContent).toContain('remains unfinished'));
 expect([...host.querySelectorAll('button')].some(b=>b.textContent==='Retry same setup request')).toBe(false);expect(requests).toHaveLength(1);
});
it('fails closed with missing encrypted recovery, unavailable feature or expired preview',async()=>{
 access=null;await act(async()=>root.render(<Harness/>));expect(host.querySelector('[aria-label="Patient name"]')).toBeNull();expect(button('Check patient setup').disabled).toBe(true);expect(fetch).not.toHaveBeenCalled();await act(async()=>root.render(<Harness enabled={false}/>));expect(host.textContent).toContain('Setup unavailable');
 await newJournal();await act(async()=>root.render(<Harness/>));await wait(()=>expect(button('Check patient setup').disabled).toBe(false));await search();const original=receipts.get(requests[0].idempotency_key)!;const expiredAt=Date.now()-1;
 const expired={...original,preview:{...original.preview!,checked_at:new Date(expiredAt-300000).toISOString(),expires_at:new Date(expiredAt).toISOString()}};receipts.set(original.request_key,expired);await reopen();await click('Restore scheduling patient draft');await click('Check saved patient details');
 await wait(()=>expect(host.textContent).toContain('choices expired'));expect(host.querySelector('[aria-label="Patient matches"]')).toBeNull();
});
it('rejects malformed choices, excessive matches and altered command bindings while preserving existing ciphertext',async()=>{
 const command:SchedulingPatientCommand={action:'preview',expected_revision:3,idempotency_key:uuid(90),search:{kind:'search',query:'Shawn',birth_date:null}},p=await preview(command);
 await expect(validateSchedulingPatientReceipt({...p,preview:{...p.preview!,choices:Array.from({length:6},()=>p.preview!.choices[0])}})).rejects.toMatchObject({status:502});
 await expect(validateSchedulingPatientReceipt({...p,preview:{...p.preview!,choices:[{...p.preview!.choices[0],display_name:'Changed label'}]}})).rejects.toMatchObject({status:502});
 expect(validSchedulingPatientCommand({...command,patient_id:uuid(91)})).toBe(false);expect(validSchedulingPatientCommand({...command,search:{...command.search,birth_date:'2020-02-30'}})).toBe(false);
 const record:SchedulingPatientRecovery={version:1,workspace_id:workspace.id,appointment_id:workspace.appointment_id,query:'Shawn',birth_date:null,preview:p,saved:null,selected_choice_ref:null,pending:command};
 await journal.load(address);await journal.persist(address,{kind:'editor',workspaceId:workspace.id,editor:'scheduling-patient',data:record,pending:command.idempotency_key});
 await expect(validateSchedulingPatientRecovery({...record,workspace_id:uuid(999)},workspace.id)).rejects.toMatchObject({code:'integrity'});
 expect((await journal.load(address))?.kind).toBe('editor');
});
it('hides exact patient labels when the feature is paused and requires fresh inspection before showing them again',async()=>{
 await mount();await search();expect(host.textContent).toContain('Shawn Café');await act(async()=>root.render(<Harness enabled={false}/>));expect(host.textContent).not.toContain('Shawn Café');
 await act(async()=>root.render(<Harness enabled/>));expect(host.textContent).not.toContain('Shawn Café');await click('Check saved patient details');await wait(()=>expect(host.textContent).toContain('Shawn Café'));
 const same=identity;await act(async()=>root.render(<Harness auth={{mode:'clerk_jwt',getToken:async()=> 'different-owner'}}/>));expect(host.textContent).not.toContain('Shawn Café');
 await act(async()=>root.render(<Harness auth={same}/>));expect(host.textContent).not.toContain('Shawn Café');expect(host.textContent).toContain('details are withheld');
});
it.each([401,403,404,426])('withholds patient identity on current authority refusal %s',async status=>{
 await mount();await search();vi.stubGlobal('fetch',vi.fn(async()=>new Response('',{status})));await click('Check saved patient details');await wait(()=>expect(denied).toHaveBeenCalled());expect(host.textContent).not.toContain('Shawn Café');expect(host.textContent).toContain('details are withheld');expect(await journal.load(address)).not.toBeNull();
});
it.each(['scheduling_patient_grant_unavailable','scheduling_patient_preview_superseded'])('withholds previously checked patient labels on structured %s refusal',async detail=>{
 await mount();await search();vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({detail}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})));
 await click('Check saved patient details');await wait(()=>expect(host.textContent).toContain('names and DOB are withheld'));expect(host.textContent).not.toContain('Shawn Café');
 expect(host.querySelector('[aria-label="Patient matches"]')).toBeNull();expect(host.textContent).not.toContain('Patient ready');expect(await journal.load(address)).not.toBeNull();
});
it('can set aside a definitely refused request only after original-key resolution proves no saved reservation',async()=>{
 await mount();await fill('Patient name','Shawn');vi.stubGlobal('fetch',vi.fn(async(_url,init)=>{const body=JSON.parse(String(init?.body));
  if(body.action==='resolve')return wire(String(_url),init!);
  requests.push(body);expect(await journal.load(address)).toMatchObject({pending:body.idempotency_key});
  return new Response(JSON.stringify({detail:'workspace_revision_conflict'}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 }));
 await click('Find patient');await wait(()=>{expect(requests).toHaveLength(1);expect(host.textContent).toContain('Keep this exact patient search');});
 expect([...host.querySelectorAll('button')].some(b=>b.textContent==='Set aside unsuccessful setup')).toBe(false);const original=requests[0];
 await click('Check saved setup result');await wait(()=>expect(button('Set aside unsuccessful setup').disabled).toBe(false));expect(requests).toHaveLength(1);
 expect(JSON.parse(String(vi.mocked(fetch).mock.calls[1][1]?.body))).toEqual({action:'resolve',kind:'preview',idempotency_key:original.idempotency_key});
 await click('Set aside unsuccessful setup');await wait(()=>expect(host.querySelector('[aria-label="Patient name"]')).toBeTruthy());expect(await journal.load(address)).toBeNull();expect(requests).toHaveLength(1);
 vi.stubGlobal('fetch',vi.fn(wire));await search();expect(requests[1].idempotency_key).not.toBe(original.idempotency_key);
});
it('matches the independently calculated compact UTF-8 command commitment and keeps encrypted data account-scoped',async()=>{
 const command:SchedulingPatientCommand={action:'preview',expected_revision:3,idempotency_key:uuid(90),search:{kind:'search',query:'Shawn Café',birth_date:null}};
 expect(await schedulingPatientRequestHash(workspace.id,command)).toBe('02bab5fa200ccc155b46f4aea95a6a0e8f6e56446c89772654f14921cde829f8');
 await mount();await fill('Patient name','Shawn Café');await fill('Date of birth (optional)','1980-04-12');await wait(async()=>expect(await journal.load(address)).not.toBeNull());
 const database=await new Promise<IDBDatabase>((resolve,reject)=>{const q=idb.open(`cosmas-private-drafts:v1:${scope}`);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
 try{
  const sealed=await new Promise<{ciphertext:ArrayBuffer}>((resolve,reject)=>{const q=database.transaction('sealed-drafts').objectStore('sealed-drafts').get(address);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
  const bytes=new TextDecoder().decode(sealed.ciphertext);expect(bytes).not.toContain('Shawn');expect(bytes).not.toContain('1980-04-12');expect(bytes).not.toContain('invented-patient-token');
  const key=await new Promise<CryptoKey>((resolve,reject)=>{const q=database.transaction('metadata').objectStore('metadata').get('draft-key-v1');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});expect(key.extractable).toBe(false);
 }finally{database.close();}
 const other=await openDraftStore({scope:'b'.repeat(64),native:false,indexedDB:idb,crypto:webcrypto});try{expect((await other.read(address)).value).toBeNull();}finally{other.close();}
});
it('keeps the original pending command when a returned saved receipt has a mismatched commitment',async()=>{
 await mount();await fill('Patient name','Shawn');vi.stubGlobal('fetch',vi.fn(async(_url,init)=>{const body=JSON.parse(String(init?.body));requests.push(body);return json({...await preview(body),request_sha256:'f'.repeat(64)});}));
 await click('Find patient');await wait(()=>expect(host.textContent).toContain('Keep this exact patient search'));expect(host.querySelector('[aria-label="Patient matches"]')).toBeNull();expect(linked).not.toHaveBeenCalled();
 expect(await journal.load(address)).toMatchObject({pending:requests[0].idempotency_key,data:{pending:requests[0]}});
});
it.each(['preview','mapping'])('hides checked %s after a same-identity connection observation and returns it only after explicit inspection',async kind=>{
 await mount();await search();if(kind==='mapping'){await select();await click('Save patient connection');await wait(()=>expect(host.textContent).toContain('Patient ready'));}
 const count=vi.mocked(fetch).mock.calls.length;await act(async()=>root.render(<Harness observationStamp={1}/>));expect(host.textContent).not.toContain('Shawn Café');expect(host.textContent).not.toContain('Patient ready');
 expect(host.querySelector('[aria-label="Patient matches"]')).toBeNull();expect(vi.mocked(fetch).mock.calls.length).toBe(count);expect(denied).not.toHaveBeenCalled();
 await click('Check saved patient details');await wait(()=>expect(host.textContent).toContain('Shawn Café'));if(kind==='mapping')expect(host.textContent).toContain('Patient ready');
 const inspect=JSON.parse(String(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.body));expect(inspect).toEqual({action:'inspect',request_id:kind==='mapping'?uuid(31):uuid(30)});expect(requests).toHaveLength(kind==='mapping'?2:1);
});
it('hides earlier patient choices when current status says link_required and allows a fresh authorized lookup',async()=>{
 await mount();await search();await click('Check patient setup');await wait(()=>expect(host.textContent).toContain('names and DOB are withheld'));expect(host.textContent).not.toContain('Shawn Café');
 expect(host.querySelector('[aria-label="Patient matches"]')).toBeNull();await click('Start a new patient search');await wait(()=>expect(host.querySelector('[aria-label="Patient name"]')).toBeTruthy());await search();expect(requests).toHaveLength(2);expect(host.textContent).toContain('Shawn Café');
});
it('allows the first patient search after checking an unmapped visit with link_required status',async()=>{
 await mount();await click('Check patient setup');await wait(()=>expect(host.textContent).toContain('Search for the patient'));
 expect(host.querySelector('[aria-label="Patient name"]')).toBeTruthy();expect(host.textContent).not.toContain('names and DOB are withheld');await search();expect(requests).toHaveLength(1);
});
it('keeps a saved patient connection available for inspection without offering a replacement search or confirmation',async()=>{
 await mount();await search();await select();await click('Save patient connection');await wait(()=>expect(host.textContent).toContain('Patient ready'));
 expect(host.querySelector('[aria-label="Patient name"]')).toBeNull();expect(host.querySelector('[aria-label="Patient matches"]')).toBeNull();
 expect([...host.querySelectorAll('button')].some(b=>['Start a new patient search','Save patient connection','Find patient'].includes(b.textContent??''))).toBe(false);
 expect(host.textContent).toContain('practice administrator');const original=await journal.load(address);await click('Check saved patient details');await wait(()=>expect(host.textContent).toContain('Patient ready'));
 expect(requests).toHaveLength(2);expect(await journal.load(address)).toEqual(original);
});
it('explains an existing mapping refusal while retaining the exact request until explicit absent-key resolution and set-aside',async()=>{
 await mount();await fill('Patient name','Shawn');vi.stubGlobal('fetch',vi.fn(async(url,init)=>{const command=JSON.parse(String(init?.body));if(command.action==='resolve')return wire(String(url),init!);
  requests.push(command);expect(await journal.load(address)).toMatchObject({pending:command.idempotency_key,data:{pending:command}});
  return new Response(JSON.stringify({detail:'scheduling_patient_mapping_review_required'}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 }));await click('Find patient');await wait(()=>expect(host.textContent).toContain('practice administrator'));const original=requests[0];
 expect(host.querySelector('[aria-label="Patient name"]')).toBeNull();expect(host.textContent).not.toContain('Patient ready');expect(await journal.load(address)).toMatchObject({pending:original.idempotency_key});
 expect([...host.querySelectorAll('button')].some(b=>b.textContent==='Set aside unsuccessful setup')).toBe(false);await click('Check saved setup result');await wait(()=>expect(button('Set aside unsuccessful setup').disabled).toBe(false));
 expect(requests).toHaveLength(1);await click('Set aside unsuccessful setup');await wait(()=>expect(host.querySelector('[aria-label="Patient name"]')).toBeTruthy());expect(await journal.load(address)).toBeNull();expect(requests).toHaveLength(1);
});
it('aborts a stale pending confirmation after observation refresh and keeps its exact encrypted key for explicit resolution',async()=>{
 await mount();await search();await select();let finish!:()=>void;const held=new Promise<void>(resolve=>finish=resolve);let capturedSignal:AbortSignal|undefined;
 vi.stubGlobal('fetch',vi.fn(async(url,init)=>{const command=JSON.parse(String(init?.body));if(command.action!=='confirm')return wire(String(url),init!);
  requests.push(command);expect(await journal.load(address)).toMatchObject({pending:command.idempotency_key,data:{pending:command}});receipts.set(command.idempotency_key,await confirmed(command));capturedSignal=init?.signal??undefined;await held;return json(receipts.get(command.idempotency_key));
 }));await click('Save patient connection');await wait(()=>expect(requests).toHaveLength(2));const original=requests[1];
 await act(async()=>root.render(<Harness observationStamp={1}/>));await wait(()=>expect(capturedSignal?.aborted).toBe(true));await wait(()=>expect(button('Check saved setup result').disabled).toBe(false));
 expect(host.textContent).not.toContain('Shawn Café');expect(linked).not.toHaveBeenCalled();expect(await journal.load(address)).toMatchObject({pending:original.idempotency_key,data:{pending:original}});
 await act(async()=>finish());expect(linked).not.toHaveBeenCalled();await click('Check saved setup result');await wait(()=>expect(host.textContent).toContain('Patient ready'));
 expect(requests).toHaveLength(2);expect(linked).toHaveBeenCalledOnce();expect(JSON.parse(String(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.body))).toEqual({action:'resolve',kind:'confirm',idempotency_key:original.idempotency_key});
});
it('retains the exact pending confirmation if freshness changes during the encrypted completion commit',async()=>{
 await mount();await search();await select();let finish!:()=>void,held=false;const release=new Promise<void>(resolve=>finish=resolve);
 afterWrite=async value=>{const body=value?.body as {data?:SchedulingPatientRecovery}|undefined;if(body?.data?.saved&&!body.data.pending&&!held){held=true;await release;}};
 await click('Save patient connection');await wait(()=>expect(held).toBe(true));const original=requests[1];await act(async()=>root.render(<Harness observationStamp={1}/>));
 expect(host.textContent).not.toContain('Shawn Café');expect(linked).not.toHaveBeenCalled();await act(async()=>finish());await wait(()=>expect(button('Check saved setup result').disabled).toBe(false));
 expect(await journal.load(address)).toMatchObject({pending:original.idempotency_key,data:{pending:original}});expect(requests).toHaveLength(2);expect(linked).not.toHaveBeenCalled();
 afterWrite=null;await click('Check saved setup result');await wait(()=>expect(host.textContent).toContain('Patient ready'));expect(linked).toHaveBeenCalledOnce();expect(requests).toHaveLength(2);
});

it('withholds earlier patient choices during an unresolved confirmation and retains its exact encrypted command through reopen',async()=>{
 await mount();await search();await select();let finish!:()=>void;const held=new Promise<void>(resolve=>finish=resolve);
 vi.stubGlobal('fetch',vi.fn(async(url,init)=>{const command=JSON.parse(String(init?.body));if(command.action!=='confirm')return wire(String(url),init!);
  requests.push(command);expect(await journal.load(address)).toMatchObject({pending:command.idempotency_key,data:{pending:command}});await held;
  return new Response(JSON.stringify({detail:'scheduling_patient_response_unconfirmed'}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 }));await click('Save patient connection');await wait(()=>expect(requests).toHaveLength(2));const original=requests[1];
 expect(host.querySelector('[aria-label="Patient matches"]')).toBeNull();expect(host.textContent).not.toContain('Shawn Café');expect(host.textContent).not.toContain('Shawn Other');
 await act(async()=>finish());await wait(()=>expect(host.textContent).toContain('Patient setup could not be confirmed'));expect(host.textContent).not.toContain('Shawn Café');expect(linked).not.toHaveBeenCalled();
 expect(await journal.load(address)).toMatchObject({pending:original.idempotency_key,data:{pending:original,selected_choice_ref:uuid(11),preview:{preview:{choices:expect.arrayContaining([expect.objectContaining({display_name:'Shawn Café'})])}}}});
 await reopen();await click('Restore scheduling patient draft');expect(host.textContent).not.toContain('Shawn Café');expect(requests).toHaveLength(2);
 await click('Check saved setup result');await wait(()=>expect(host.textContent).toContain('No saved request was found'));expect(requests).toHaveLength(2);expect(await journal.load(address)).toMatchObject({pending:original.idempotency_key,data:{pending:original}});
});

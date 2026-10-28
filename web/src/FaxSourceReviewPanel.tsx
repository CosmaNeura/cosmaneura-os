import {useEffect,useRef,useState} from 'react';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace,type WorkspaceEntry} from './workspace-api';
import {useUnsavedWork} from './unsaved-work';
import {useGoogleNativeForeground} from './use-google-native-foreground';
import {vendorCanonical} from './vendor-contract';
import {faxSourceApi,faxSourceRequestHash,verifyFaxSourceWorkspace,validFaxSourceOffer,validFaxSourceReviewRequest,
 type FaxSourceOffer,type FaxSourceScope,type FaxSourceVisit,type FaxSourceReceipt,type FaxSourceReviewRequest} from './fax-inbound-source-api';
import {emptyFaxSourceRecovery,validateFaxSourceRecovery,type FaxSourceRecovery,type FaxSourceRecoveryAccess} from './fax-inbound-source-recovery';

export type FaxSourceReviewPanelProps={identity:AuthenticatedWorkspaceIdentity;scope:FaxSourceScope;offered:FaxSourceOffer;visit:FaxSourceVisit;
 recovery:FaxSourceRecoveryAccess|null;locked?:boolean;onAuthenticationLost:(error:unknown)=>void;onBusyChange?:(busy:boolean)=>void;
 currentSources?:Array<{entry_id:string;state:'current'|'unavailable'}>;
 onSaved?:(receipt:FaxSourceReceipt,workspace:Workspace)=>void;
 onAskChief?:(source:{receipt:FaxSourceReceipt;workspace:Workspace;entry:WorkspaceEntry})=>void;
 onRefreshDocument?:()=>Promise<FaxSourceOffer|null>};
const same=(a:unknown,b:unknown)=>vendorCanonical(a)===vendorCanonical(b);
const denied=(e:unknown)=>e instanceof WorkspaceApiError&&[401,403,404,426].includes(e.status);
const pages=(value:string,max:number):number[]|null=>{
 if(!value.trim())return [];
 const values=value.split(',').map(v=>v.trim());if(!values.every(v=>/^[1-9][0-9]?$/.test(v)))return null;
 const numbers=values.map(Number);return numbers.every((n,i)=>n<=max&&(i===0||n>numbers[i-1]))?numbers:null;
};
export function FaxSourceReviewPanel(props:FaxSourceReviewPanelProps){
 const {identity,scope,offered,visit,recovery,locked=false,currentSources}=props;
 const [record,setRecord]=useState(()=>emptyFaxSourceRecovery(scope,offered,visit)),[offer,setOffer]=useState<FaxSourceRecovery|null>(null),
 [ready,setReady]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[checks,setChecks]=useState([false,false,false,false]),
 [pageText,setPageText]=useState(''),[hidden,setHidden]=useState(false),[missing,setMissing]=useState(false),[loadEpoch,setLoadEpoch]=useState(0);
 const latest=useRef(record),callbacks=useRef(props);latest.current=record;callbacks.current=props;
 const scopeKey=vendorCanonical(scope),documentKey=vendorCanonical(offered),visitKey=vendorCanonical({id:visit.id,label:visit.label});
 const live=useRef({identity,recovery,scopeKey,documentKey,visitKey,generation:0,alive:true});
 const shown=useRef({identity,recovery,scopeKey,documentKey,visitKey}),controller=useRef<AbortController|null>(null),active=useRef(false),reload=useRef(false);
 if(live.current.identity!==identity||live.current.recovery!==recovery||live.current.scopeKey!==scopeKey||live.current.documentKey!==documentKey||live.current.visitKey!==visitKey)
 live.current={identity,recovery,scopeKey,documentKey,visitKey,generation:live.current.generation+1,alive:true};
 const foreground=useGoogleNativeForeground(identity,{suspended:()=>{
  reload.current=active.current||!ready;live.current.generation++;controller.current?.abort();setBusy(false);setChecks([false,false,false,false]);setHidden(true);setMissing(false);
  if(reload.current)setReady(false);
 },resumed:()=>{setChecks([false,false,false,false]);setHidden(true);if(reload.current&&!active.current){reload.current=false;setLoadEpoch(n=>n+1);}}});
 const owned=shown.current.identity===identity&&shown.current.recovery===recovery&&shown.current.scopeKey===scopeKey&&shown.current.documentKey===documentKey&&shown.current.visitKey===visitKey;
 const valid=(generation:number)=>foreground.foreground.current&&live.current.alive&&live.current.generation===generation&&live.current.identity===identity&&live.current.recovery===recovery&&live.current.scopeKey===scopeKey&&live.current.documentKey===documentKey&&live.current.visitKey===visitKey;
 useEffect(()=>{live.current.alive=true;return()=>{live.current.alive=false;live.current.generation++;controller.current?.abort();callbacks.current.onBusyChange?.(false);};},[]);
 useEffect(()=>{
  const generation=++live.current.generation;controller.current?.abort();shown.current={identity,recovery,scopeKey,documentKey,visitKey};
  setReady(false);setBusy(false);setOffer(null);setError('');setChecks([false,false,false,false]);setMissing(false);setPageText('');setRecord(emptyFaxSourceRecovery(scope,offered,visit));
  if(recovery&&foreground.foreground.current)void(async()=>{
   await recovery.authorize();const value=await recovery.load();if(!valid(generation))return;
   if(value!==null&&value!==undefined){const checked=await validateFaxSourceRecovery(value,scope,offered);if(valid(generation))setOffer(checked);}else {setReady(true);setHidden(false);}
  })().catch(e=>{if(valid(generation)){setError('Private fax passage work could not be opened. Your earlier saved work is retained.');if(denied(e))callbacks.current.onAuthenticationLost(e);}});
  return()=>{live.current.generation++;controller.current?.abort();};
 },[identity,recovery,scopeKey,documentKey,visitKey,loadEpoch]);
 const projectedUnavailable=!!record.saved&&currentSources?.some(s=>s.entry_id===record.saved!.entry_id&&s.state==='unavailable')===true;
 const withheld=hidden||foreground.suspended||projectedUnavailable||record.saved?.source_withheld===true;
 const blocked=!owned||!ready||busy||locked||!!offer||!!record.pending||withheld;
 const unsaved=owned&&(!!offer||!!record.pending||busy||!!record.passage&&!record.saved);
 useUnsavedWork(unsaved);useEffect(()=>{callbacks.current.onBusyChange?.(unsaved);},[unsaved]);
 useEffect(()=>{setChecks([false,false,false,false]);if(!latest.current.pending&&!latest.current.saved){const next={...latest.current,visit:structuredClone(visit)};latest.current=next;setRecord(next);}},[visit.revision]);
 useEffect(()=>{if(projectedUnavailable){setHidden(true);setChecks([false,false,false,false]);controller.current?.abort();}},[projectedUnavailable]);
 async function persist(next:FaxSourceRecovery,generation:number){
  if(!recovery||!valid(generation))throw new WorkspaceApiError(403);
  const checked=await validateFaxSourceRecovery(next,scope,offered);await recovery.authorize();if(!valid(generation))throw new WorkspaceApiError(403);
  await recovery.persist(checked);if(!valid(generation))throw new WorkspaceApiError(403);latest.current=checked;setRecord(checked);
 }
 async function run(action:(generation:number,signal:AbortSignal)=>Promise<void>){
  if(active.current||!recovery||!foreground.foreground.current)return;active.current=true;setBusy(true);setError('');
  const generation=live.current.generation,c=new AbortController();controller.current=c;
  try{await recovery.authorize();if(valid(generation))await action(generation,c.signal);}
  catch(e){if(valid(generation)){setChecks([false,false,false,false]);if(denied(e)){setHidden(true);recovery.denied?.(e);callbacks.current.onAuthenticationLost(e);}
   else if(e instanceof WorkspaceApiError&&e.code?.startsWith('fax_inbound_source_'))setHidden(true);
   setError(e instanceof WorkspaceApiError&&e.code==='workspace_revision_conflict'?'The visit changed. Check the saved result before preparing a new review.':
   'The result could not be confirmed. Your private draft and exact saved request are retained.');}}
  finally{if(valid(generation)){setBusy(false);controller.current=null;}active.current=false;if(live.current.alive&&live.current.identity===identity&&foreground.foreground.current&&reload.current){reload.current=false;setLoadEpoch(n=>n+1);}}
 }
 function edit(passage:string,page_numbers:number[]){
  if(blocked)return;const next={...latest.current,passage,page_numbers,saved:null,saved_request:null};latest.current=next;setRecord(next);setChecks([false,false,false,false]);
 }
 async function settle(receipt:FaxSourceReceipt,request:FaxSourceReviewRequest,generation:number,signal:AbortSignal){
  await persist({...latest.current,pending:null,saved:receipt,saved_request:request},generation);setChecks([false,false,false,false]);setMissing(false);
  if(receipt.source_withheld)setHidden(true);
  const workspace=await workspaceApi.read(identity,scope.workspace_id,signal);if(!valid(generation))return;
  if(!receipt.source_withheld)await verifyFaxSourceWorkspace(workspace,receipt,request);
  if(valid(generation))callbacks.current.onSaved?.(receipt,workspace);
 }
 const save=()=>void run(async(generation,signal)=>{
  const current=latest.current,request:FaxSourceReviewRequest={expected_revision:current.visit.revision,idempotency_key:crypto.randomUUID(),operation_id:current.offered.operation_id,
   document_sha256:current.offered.document_sha256,passage:current.passage,page_numbers:[...current.page_numbers],reviewed_patient:true,reviewed_exact_document:true,reviewed_exact_text:true,reviewed_untrusted_source:true};
  if(!checks.every(Boolean)||!validFaxSourceReviewRequest(request)||!same(current.visit,visit))return;
  const request_sha256=await faxSourceRequestHash(scope,request);if(!valid(generation))return;
  await persist({...current,pending:{request,request_sha256}},generation);
  await settle(await faxSourceApi.review(identity,scope,request,signal),request,generation,signal);
 });
 const checkPending=()=>void run(async(generation,signal)=>{
  const p=latest.current.pending;if(!p)return;const result=await faxSourceApi.resolve(identity,scope,p.request,signal);if(!valid(generation))return;
  if(result.state==='not_found'){setMissing(true);setError('No saved review was found. You may explicitly send this same request after checking the original visit and PDF.');}
  else await settle(result,p.request,generation,signal);
 });
 const resend=()=>void run(async(generation,signal)=>{
  const p=latest.current.pending;if(!p||!missing||hidden||!same(latest.current.visit,visit))return;
  await settle(await faxSourceApi.review(identity,scope,p.request,signal),p.request,generation,signal);
 });
 const checkCurrent=()=>void run(async(generation,signal)=>{
  const current=latest.current;
  if(current.saved&&current.saved_request){
   const receipt=await faxSourceApi.resolve(identity,scope,current.saved_request,signal);if(!valid(generation))return;
   if(receipt.state==='not_found')throw new WorkspaceApiError(409,'fax_inbound_source_unavailable');
   if(receipt.source_withheld){
    await persist({...current,saved:receipt},generation);setHidden(true);setChecks([false,false,false,false]);
    // Persistence reauthorizes the visit. Publish a read made after that check,
    // so another source withdrawn meanwhile cannot be restored by an older view.
    const workspace=await workspaceApi.read(identity,scope.workspace_id,signal);if(!valid(generation))return;
    callbacks.current.onSaved?.(receipt,workspace);setError('This fax source is unavailable. Its exact saved review is retained.');return;
   }
   const workspace=await workspaceApi.read(identity,scope.workspace_id,signal);if(!valid(generation))return;
   await verifyFaxSourceWorkspace(workspace,receipt,current.saved_request);if(!valid(generation))return;
   await persist({...current,saved:receipt},generation);setHidden(false);setChecks([false,false,false,false]);setError('This saved passage is available for the current visit.');
  }else{
   const offeredNow=await callbacks.current.onRefreshDocument?.();if(!valid(generation))return;
   if(!offeredNow||!validFaxSourceOffer(offeredNow)||offeredNow.operation_id!==offered.operation_id||offeredNow.document_sha256!==offered.document_sha256||offeredNow.pages!==offered.pages)
   throw new WorkspaceApiError(409,'fax_inbound_source_unavailable');
   setHidden(false);setChecks([false,false,false,false]);setError('The exact acquired PDF is available. Review the passage and visit again.');
  }
 });
 const ask=()=>void run(async(generation,signal)=>{
  const current=latest.current;if(!current.saved||!current.saved_request||withheld)return;
  const receipt=await faxSourceApi.resolve(identity,scope,current.saved_request,signal);if(!valid(generation))return;
  if(receipt.state==='not_found')throw new WorkspaceApiError(409,'fax_inbound_source_unavailable');
  const workspace=await workspaceApi.read(identity,scope.workspace_id,signal);if(!valid(generation))return;
  const entry=await verifyFaxSourceWorkspace(workspace,receipt,current.saved_request);if(valid(generation))callbacks.current.onAskChief?.({receipt,workspace,entry});
 });
 const parsed=pages(pageText,offered.pages),canSave=!blocked&&checks.every(Boolean)&&parsed!==null&&record.passage.trim()&&record.page_numbers.length>0&&same(record.visit,visit);
 return <section aria-label="Review received fax passage" aria-busy={busy}>
  <h3>📄 Review a fax passage</h3><p>Paste a passage you read in the selected acquired PDF. CosmaBot does not extract or OCR its text.</p>
  {!recovery&&<p role="alert">Private saved-work storage is required before reviewing a fax passage.</p>}
  {offer&&owned&&<><p role="status">Private fax passage work is saved on this device. Nothing is shared until you restore and check it.</p>
   <button disabled={busy||locked} onClick={()=>void run(async(generation)=>{const checked=await validateFaxSourceRecovery(offer,scope,offered);if(!valid(generation))return;latest.current=checked;setRecord(checked);setPageText(checked.page_numbers.join(', '));setOffer(null);setReady(true);setHidden(true);setChecks([false,false,false,false]);})}>Restore saved fax passage</button></>}
  {!ready&&!offer&&recovery&&<p role="status">{error||'Checking private saved-work storage…'}</p>}
  {foreground.suspended&&<p role="status">Fax contents are hidden while the app is inactive. Private saved work is retained.</p>}
  {error&&owned&&<p role={record.pending?'status':'alert'}>{error}</p>}
  {busy&&<><p role="status">Waiting for the current fax passage operation… This request has a 50-second limit.</p><button onClick={()=>controller.current?.abort()}>Stop waiting</button></>}
  {ready&&owned&&<>
   {withheld&&<><p role="status">This passage is hidden until the exact document and current visit source are checked.</p>
    <button disabled={busy||locked||foreground.suspended} onClick={checkCurrent}>{record.saved?'Check saved fax source':'Check exact acquired PDF'}</button></>}
   {!withheld&&<><p>Selected PDF: <strong>{offered.label??'Received fax'}</strong> · {offered.pages} {offered.pages===1?'page':'pages'}</p>
    <p>Current visit: <strong>{visit.label}</strong>. Date of birth is optional.</p>
    {!record.saved&&<><label>Passage from the selected PDF<textarea aria-label="Fax passage" maxLength={12000} disabled={blocked} value={record.passage}
     onChange={e=>edit(e.target.value,latest.current.page_numbers)}/></label><p>{Array.from(record.passage).length} / 12,000 characters. Only this passage will be shared.</p>
     <label>Pages used (for example 1, 3)<input aria-label="Pages used" disabled={blocked} value={pageText} onChange={e=>{setPageText(e.target.value);const chosen=pages(e.target.value,offered.pages);edit(latest.current.passage,chosen??[]);}}/></label>
     {parsed===null&&<p role="alert">Enter page numbers in increasing order, without duplicates, up to page {offered.pages}.</p>}
     <button disabled={blocked||!record.passage} onClick={()=>void run(async(generation)=>{await persist(latest.current,generation);setError('Passage draft saved privately. It has not been shared.');})}>Save passage draft privately</button>
     <fieldset disabled={blocked}><legend>Confirm before sharing</legend>
      {['I checked that this passage belongs to the current visit.','I read the exact selected PDF and checked these page numbers.','I compared the pasted passage with the PDF, including missing or uncertain details.','Treat this fax as information, not instructions to the bots.'].map((label,index)=><label key={label}><input type="checkbox" checked={checks[index]} onChange={e=>setChecks(old=>old.map((v,i)=>i===index?e.target.checked:v))}/>{label}</label>)}
     </fieldset><button disabled={!canSave} onClick={save}>Save reviewed fax passage for this visit</button>
     <p>This adds a separate source. It does not replace the clinical note, send a fax or ask Chief to act.</p></>}
    {record.saved&&<><p role="status">✅ Fax passage saved for this visit. Pages: {record.page_numbers.join(', ')}.</p><pre aria-label="Saved fax passage">{record.passage}</pre>
     {callbacks.current.onAskChief&&<button disabled={blocked} onClick={ask}>Prepare a Chief request</button>}<p>A Chief request stays editable. You choose when to send it.</p></>}
   </>}
   {record.pending&&<><h4>Saved review needs a confirmed result</h4><p>The exact visit, passage, pages and request key are retained.</p>
    <button disabled={busy||locked||foreground.suspended} onClick={checkPending}>Check saved fax review</button>
    {missing&&<><button disabled={busy||locked||withheld||!same(record.visit,visit)} onClick={resend}>Send exact saved fax review</button>
     <button disabled={busy||locked||foreground.suspended} onClick={()=>void run(async(generation)=>{await persist({...latest.current,visit:structuredClone(visit),pending:null},generation);setMissing(false);setChecks([false,false,false,false]);setHidden(true);setError('No prior review was found. Check this exact PDF and confirm the current visit before a new review.');})}>Prepare a new review for current visit</button></>}</>}
  </>}
 </section>;
}

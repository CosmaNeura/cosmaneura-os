import {efaxFaxHash,efaxPublicHash,validateEFaxPending,type EFaxPending,type EFaxReceipt,type EFaxProposal,type EFaxScope} from '../src/efax-inbound-api';
import {EFAX_SOURCE_LABEL,EFAX_SOURCE_WITHHELD_LABEL,efaxSourceRequestHash,validEFaxSourceReviewRequest,type EFaxSourceReceipt,type EFaxSourceReviewRequest} from '../src/efax-inbound-source-api';
import {vendorCanonical,vendorSha256} from '../src/vendor-contract';
import {teamClosed} from '../src/team-setup-request';
import {CONNECTION_IDS} from '../src/connection-catalog-api';
import {readinessFixture} from '../src/connection-readiness-fixture';
import {WorkspaceApiError,type Workspace} from '../src/workspace-api';

export const RECEIVED_FAX_PASSAGE='Invented follow-up: the medication list and contact consent are still unconfirmed. Please clarify these details with the patient.';
const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const ids={installation:uuid(9701),grant:uuid(9702),fax:uuid(9703),observation:uuid(9704),ticket:uuid(9705),revision:uuid(9706),operation:uuid(9707)};
/** One valid, entirely invented PDF; this fixture never reads or OCRs a real file. */
export function receivedFaxPdf():Uint8Array{
 const lines=['Invented received fax','Jordan Cypress - synthetic visit; DOB unavailable.',
  'Invented follow-up: the medication list and contact consent are still',
  'unconfirmed. Please clarify these details with the patient.'];
 const stream='BT /F1 12 Tf 48 740 Td '+lines.map((line,index)=>(index?'0 -24 Td ':'')+'('+line+') Tj').join('\n')+' ET\n';
 const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
  '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
  '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',`<< /Length ${stream.length} >>\nstream\n${stream}endstream`];
 let text='%PDF-1.4\n';const offsets=[0];
 objects.forEach((object,index)=>{offsets.push(text.length);text+=`${index+1} 0 obj\n${object}\nendobj\n`;});
 const xref=text.length;text+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`;
 for(const offset of offsets.slice(1))text+=String(offset).padStart(10,'0')+' 00000 n \n';
 text+=`trailer\n<< /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
 return new TextEncoder().encode(text);
}
type Saved={hash:string;kind:string;value:EFaxReceipt|EFaxSourceReceipt};
type State={scope:EFaxScope;grant:boolean;images:boolean;lost:string[];ledger:[string,Saved][];proposal:EFaxProposal|null;approved:boolean};
export type ReceivedFaxStats={observations:number;proposals:number;decisions:number;acquisitions:number;documents:number;reviews:number;resolves:number;externalCalls:number;requests:{path:string;method:string;body:unknown}[]};

/** Tab-local synthetic ledger. The real eFax request, receipt and PDF validators run unchanged. */
export function receivedFaxRehearsal(read:()=>Workspace,write:(value:Workspace)=>void,storageKey:string,reset:boolean,scope:EFaxScope){
 const key=storageKey+':received-fax',stored=reset?null:sessionStorage.getItem(key);
 const state:State=stored?JSON.parse(stored):{scope:structuredClone(scope),grant:true,images:true,lost:[],ledger:[],proposal:null,approved:false};
 const ledger=new Map(state.ledger),same=(a:unknown,b:unknown)=>vendorCanonical(a)===vendorCanonical(b),current=()=>same(scope,state.scope);
 const persist=()=>sessionStorage.setItem(key,JSON.stringify({...state,ledger:[...ledger]}));if(current())persist();
 const stats:ReceivedFaxStats={observations:0,proposals:0,decisions:0,acquisitions:0,documents:0,reviews:0,resolves:0,externalCalls:0,requests:[]};
 const pdf=receivedFaxPdf(),pdfHash=vendorSha256(pdf),hash=(value:unknown)=>vendorSha256(new TextEncoder().encode(vendorCanonical(value)));
 const scenario=()=>new URLSearchParams(location.search).get('scenario')??'received-fax-happy';
 const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 const fail=(code='efax_inbound_source_unavailable',status=409):never=>{throw new WorkspaceApiError(status,code);};
 const access=(images=false)=>{if(!current()||!state.grant)fail('efax_inbound_grant_unavailable');if(images&&state.images!==true)fail('efax_inbound_grant_unavailable');};
 const withhold=()=>{const workspace=read();write({...workspace,entries:workspace.entries.map(entry=>entry.kind==='efax_inbound_source'?{...entry,content:'',source_label:EFAX_SOURCE_WITHHELD_LABEL,fax_source_state:'unavailable'}:entry)});};
 const withdraw=()=>{state.grant=false;persist();withhold();};
 Object.assign(window,{receivedFaxStats:stats,receivedFaxControls:{withdraw}});
 const acquisition=()=>[...ledger.values()].find(row=>row.kind==='acquire')?.value as EFaxReceipt|undefined;
 const retain=async(key:string,kind:string,body:unknown,work:()=>Promise<Saved['value']>)=>{
  const fingerprint=await hash(body),old=ledger.get(key);
  if(old){if(old.hash!==fingerprint||old.kind!==kind)fail('efax_inbound_idempotency_conflict');return structuredClone(old.value);}
  const value=await work();ledger.set(key,{hash:fingerprint,kind,value});persist();return structuredClone(value);
 };
 const lose=(kind:'acquire'|'review')=>{if(scenario()===`received-fax-lost-${kind}`&&!state.lost.includes(kind)){state.lost.push(kind);persist();throw new Error(`Invented lost successful ${kind} response`);}};
 const command=async(p:EFaxPending):Promise<EFaxReceipt>=>{
  const base={contract_version:1 as const,scope:structuredClone(scope),kind:p.kind,idempotency_key:p.request.idempotency_key,receipt_id:crypto.randomUUID(),request_sha256:await hash(p),public_request_sha256:await efaxPublicHash(scope,p)};
  if(p.kind==='grant'){if(p.request.installation_id!==ids.installation)fail();state.grant=true;state.images=p.request.image_enabled;if(!state.images)withhold();return {...base,state:'granted',grant_id:ids.grant,label:'Invented eFax account',metadata_enabled:true,image_enabled:p.request.image_enabled,expires_at:p.request.expires_at};}
  access();
  if(p.kind==='revoke'){if(p.request.grant_id!==ids.grant)fail();withdraw();return {...base,state:'revoked',grant_id:ids.grant};}
  if(p.kind==='observe'){
   if(p.request.grant_id!==ids.grant)fail();stats.observations++;
   const completed=new Date(Date.parse(p.request.ends_at)-3600000).toISOString(),source_sha256=await hash(p.request);
   const fax={fax_id:ids.fax,size:pdf.length,duration:10,pages:1,image_downloaded:!!acquisition(),completed_timestamp:completed,destination_fax_number:'+12025550101',originating_fax_number:'+12025550102',originating_fax_tsid:'Invented clinic sender',fax_status:'STORED' as const};
   return {...base,state:'observed',grant_id:ids.grant,observation_id:ids.observation,source_sha256,snapshot:{request:{request_id:ids.observation,starts_at:p.request.starts_at,ends_at:p.request.ends_at,limit:25,offset:0},first_record:0,last_record:0,items:scenario()==='received-fax-empty'?[]:[fax],observed_at:p.request.ends_at,raw_sha256:await hash(fax),source_sha256,scope:'one_received_metadata_page',inbox_complete:false,continuation:'unknown'}};
  }
  if(p.kind==='propose'){
   const observed=[...ledger.values()].find(row=>row.kind==='observe'&&(row.value as EFaxReceipt).observation_id===p.request.observation_id)?.value as EFaxReceipt|undefined;
   const fax=observed?.snapshot?.items.find(item=>item.fax_id===p.request.fax_id);
   if(!fax||p.request.grant_id!==ids.grant||p.request.observation_sha256!==observed?.source_sha256||p.request.fax_sha256!==await efaxFaxHash(fax))return fail('efax_inbound_source_changed');
   if(state.proposal)fail('efax_inbound_proposal_exists');stats.proposals++;
   const command_sha256=await hash(p),expires_at=new Date(Date.now()+3600000).toISOString();
   state.proposal={contract_version:1,scope:structuredClone(scope),ticket_id:ids.ticket,revision_id:ids.revision,version:1,state:'pending_approval',command_sha256,expires_at,side_effect:'marks_fax_downloaded_or_read',source_withheld:false,fax,fax_sha256:await efaxFaxHash(fax),observation_id:ids.observation,observation_sha256:observed!.source_sha256!,account_label:'Invented eFax account'};
   return {...base,state:'approval_required',ticket_id:ids.ticket,revision_id:ids.revision,version:1,command_sha256,expires_at,side_effect:'marks_fax_downloaded_or_read'};
  }
  const proposal=state.proposal;
  if(!proposal||p.request.ticket_id!==ids.ticket||p.request.revision_id!==ids.revision||Date.now()>=Date.parse(proposal.expires_at))return fail('efax_inbound_proposal_unavailable');
  if(p.kind==='decide'){
   if(proposal.state!=='pending_approval'||p.request.expected_version!==1)fail('efax_inbound_proposal_changed');
   stats.decisions++;state.approved=p.request.choice==='approve';proposal.state=state.approved?'approved':'rejected';proposal.version=2;
   return {...base,state:state.approved?'approved':'rejected',ticket_id:ids.ticket,revision_id:ids.revision,version:2,decision_id:crypto.randomUUID(),approval_sha256:state.approved?await hash({proposal:proposal.command_sha256,reviewed:true}):null};
  }
  const approved=[...ledger.values()].find(row=>row.kind==='decide'&&(row.value as EFaxReceipt).state==='approved')?.value as EFaxReceipt|undefined;
  if(!state.approved||p.request.expected_version!==2||p.request.approval_sha256!==approved?.approval_sha256||acquisition())fail('efax_inbound_approval_unavailable');
  stats.acquisitions++;
  return {...base,state:'acquired',ticket_id:ids.ticket,revision_id:ids.revision,operation_id:ids.operation,version:3,retry_allowed:false,content_available:true,source_withheld:false,document:{sha256:await pdfHash,byte_length:pdf.length,pages:1}};
 };
 return async(path:string,init?:RequestInit):Promise<Response|null>=>{
  const method=init?.method??'GET',isScenario=scenario().startsWith('received-fax');
  if(path==='/connections/catalog'&&method==='GET'&&isScenario){
   const catalog=readinessFixture({messaging:'user_connectable'});catalog.messaging=true;
   for(const [vendor,actionId] of [['google','reviewed_email_source'],['microsoft','full_email_source']] as const)
    catalog.readiness![vendor].actions=catalog.readiness![vendor].actions.map(action=>action.id===actionId?{...action,supported:true,runtime_available:true}:action);
   catalog.readiness!.messaging={...catalog.readiness!.messaging,installed_account:'installed',runtime_available:true,actions:catalog.readiness!.messaging.actions.map(action=>({...action,runtime_available:action.id==='reviewed_received_fax'}))};
   return response({version:2,services:CONNECTION_IDS.map(id=>({id,setup_available:catalog[id],...catalog.readiness![id]}))});
  }
  if(path==='/vendor-settings/readiness'&&method==='GET'&&isScenario)return response({contract_version:1,scope,enabled:true,work_enabled:false,delivery_enabled:false,credential_access_configured:true,document_storage_configured:true,providers:['spruce','srfax','documo','efax'].map(id=>({id,installed_accounts:id==='efax'?1:0,active_accounts:id==='efax'?1:0,review_required_accounts:0,unavailable_accounts:0,prepare_enabled_accounts:0}))});
  if(path==='/vendor-settings'&&method==='GET'&&isScenario)return response({contract_version:1,scope,enabled:true,installed_accounts:[],patients:[],setups:[]});
  const source=/^\/workspaces\/([a-f0-9-]{36})\/efax-inbound-source(\/resolve)?$/.exec(path);
  if(path!=='/efax-inbound'&&!path.startsWith('/efax-inbound/')&&!source)return null;
  try{
   if(!current())fail('efax_inbound_grant_unavailable');
   const headers=new Headers(init?.headers);if(headers.get('X-Cosmas-EFax-Inbound')!=='1')fail('efax_inbound_invalid',422);
   const body=typeof init?.body==='string'?JSON.parse(init.body):null;stats.requests.push({path,method,body:structuredClone(body)});
   if(path==='/efax-inbound'&&method==='GET')return response(scenario()==='received-fax-absent'?{contract_version:1,scope,enabled:false,installations:[],grants:[]}:{contract_version:1,scope,enabled:true,installations:[{installation_id:ids.installation,label:'Invented eFax account',metadata_available:true,image_available:true}],grants:[{grant_id:ids.grant,label:'Invented eFax account',state:state.grant?'available':'unavailable',image_enabled:state.grant&&state.images===true,expires_at:'2099-10-26T18:00:00Z'}]});
   if(path.startsWith('/efax-inbound/documents/')&&method==='GET'){
    access(true);if(path!==`/efax-inbound/documents/${ids.operation}`||acquisition()?.state!=='acquired')fail();stats.documents++;
    return new Response(new Uint8Array(pdf),{headers:{'Content-Type':'application/pdf','Cache-Control':'no-store','Content-Length':String(pdf.length),'X-Content-Type-Options':'nosniff','Content-Disposition':'attachment; filename=received-fax.pdf'}});
   }
   if(path.startsWith('/efax-inbound/proposals/')&&method==='GET'){
    access();if(path!==`/efax-inbound/proposals/${ids.ticket}`||!state.proposal)fail();return response(state.proposal);
   }
   if(method!=='POST'||!body||typeof body!=='object')fail('efax_inbound_invalid',422);
   if(source){
    if(source[1]!==read().id)fail('efax_inbound_source_unavailable');
    if(source[2]){
     if(!teamClosed(body,'idempotency_key')||typeof body.idempotency_key!=='string')fail('efax_inbound_source_invalid',422);
     stats.resolves++;const row=ledger.get(body.idempotency_key);
     if(!row)return response({contract_version:1,scope:{...scope,workspace_id:read().id},idempotency_key:body.idempotency_key,state:'not_found'});
     if(row.kind!=='review')fail('efax_inbound_source_invalid');return response({...row.value,source_withheld:!state.grant||state.images!==true});
    }
    access(true);if(!validEFaxSourceReviewRequest(body))fail('efax_inbound_source_review_invalid',422);
    const request=body as EFaxSourceReviewRequest;
    const saved=await retain(request.idempotency_key,'review',{workspace_id:read().id,request},async()=>{
     const workspace=read(),image=acquisition();if(!image||image.state!=='acquired'||request.operation_id!==ids.operation||request.document_sha256!==await pdfHash||request.page_numbers.some(page=>page!==1))fail('efax_inbound_source_document_changed');
     if(request.expected_revision!==workspace.revision)fail('workspace_revision_conflict');
     const entry_id=crypto.randomUUID(),entry_revision=workspace.revision+1,sourceScope={...scope,workspace_id:workspace.id};
     const result:EFaxSourceReceipt={contract_version:1,scope:sourceScope,idempotency_key:request.idempotency_key,request_sha256:await efaxSourceRequestHash(sourceScope,request),review_id:crypto.randomUUID(),entry_id,entry_revision,operation_id:ids.operation,source_sha256:await hash({operation:ids.operation,document:await pdfHash,passage:request.passage,pages:request.page_numbers}),content_sha256:await vendorSha256(new TextEncoder().encode(request.passage)),document_sha256:await pdfHash,page_numbers:[...request.page_numbers],coverage:'human_selected_passage',extraction:'human_entered_no_ocr',source_withheld:false,state:'saved'};
     write({...workspace,revision:entry_revision,entries:[...workspace.entries,{id:entry_id,revision:entry_revision,kind:'efax_inbound_source',content:request.passage,source_label:EFAX_SOURCE_LABEL,origin:'authenticated_human',created_at:new Date().toISOString(),ticket:null,fax_source_state:'current'}]});stats.reviews++;return result;
    });lose('review');return response(saved);
   }
   if(path==='/efax-inbound/resolve'){
    if(!teamClosed(body,'idempotency_key,kind')||typeof body.idempotency_key!=='string'||typeof body.kind!=='string'||!['observation','image','command'].includes(body.kind))return fail('efax_inbound_invalid',422);
    stats.resolves++;const row=ledger.get(body.idempotency_key);
    if(!row)return response({contract_version:1,scope,idempotency_key:body.idempotency_key,kind:body.kind==='image'?'acquire':body.kind==='observation'?'observe':'recover',state:'not_found',...(body.kind==='image'?{retry_allowed:false,content_available:false,source_withheld:false,document:null}:{})});
    if(row.kind==='review'||(row.kind==='acquire'?'image':row.kind==='observe'?'observation':'command')!==body.kind)fail('efax_inbound_idempotency_conflict');
    if((!state.grant||state.images!==true)&&row.kind==='acquire')return response({...row.value,content_available:false,source_withheld:true,document:null});access();return response(row.value);
   }
   const kind=path.slice('/efax-inbound/'.length),p=validateEFaxPending({kind,request:body});
   if(p.kind!=='grant')access(['propose','decide','acquire'].includes(p.kind));
   const result=await retain(p.request.idempotency_key,p.kind,p,()=>command(p));if(p.kind==='acquire')lose('acquire');return response(result);
  }catch(error){if(error instanceof WorkspaceApiError)return response({error:{code:error.code??'efax_inbound_invalid'}},error.status);throw error;}
 };
}

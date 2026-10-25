import {ehrHash,ehrItemHash,ehrContentHash,ehrSourceContent,ehrSourceHash,ehrReviewHash,validEhrCommand,validEhrReview,ehrMatchesCommand,type EhrReceipt,type EhrWindowItem,type EhrVerifiedItem} from '../src/ehr-read-api';
import {WorkspaceApiError,type Workspace} from '../src/workspace-api';

/** Local invented-data rehearsal only. This handler never reaches a provider. */
export function ehrRehearsal(read:()=>Workspace,write:(value:Workspace)=>void,storageKey:string,reset:boolean){
 const ledgerKey=storageKey+':ehr',ledger=new Map<string,{hash:string;value:unknown}>(reset?[]:JSON.parse(sessionStorage.getItem(ledgerKey)??'[]'));
 if(reset)sessionStorage.removeItem(ledgerKey);
 const binding={connection_id:'00000000-0000-4000-8000-000000009701',binding_sha256:'b'.repeat(64)};
 const practice={label:'Invented Cypress practice',timezone:'America/New_York'};
 const stats={reads:0,reviews:0,resolves:0,inspects:0,externalCalls:0};
 Object.assign(window,{ehrRehearsalStats:stats});
 let lostReview=false;
 const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 const find=(id:string)=>[...ledger.values()].map(row=>row.value).find((value):value is EhrReceipt=>!!value&&typeof value==='object'&&'observation_id' in value&&value.observation_id===id);
 const retain=async(key:string,body:unknown,work:()=>Promise<unknown>)=>{const hash=await ehrHash(body),old=ledger.get(key);if(old){if(old.hash!==hash)throw new WorkspaceApiError(409,'idempotency_conflict');return structuredClone(old.value);}const value=await work();ledger.set(key,{hash,value});sessionStorage.setItem(ledgerKey,JSON.stringify([...ledger]));return structuredClone(value);};
 return async(path:string,init?:RequestInit):Promise<Response|null>=>{
  const review=/^\/workspaces\/([a-f0-9-]{36})\/ehr-read\/review$/.exec(path);
  if(path!=='/connections/ehr/reads'&&!review)return null;
  try{
   if(init?.method!=='POST'||typeof init.body!=='string'||new Headers(init.headers).get('X-Cosmas-Ehr-Read')!=='1')throw new WorkspaceApiError(422,'invalid_ehr_read_request');
   const body=JSON.parse(init.body);
   if(review){
    if(!validEhrReview(body)||review[1]!==read().id)throw new WorkspaceApiError(422,'invalid_ehr_read_review');stats.reviews++;
    const result=await retain(body.idempotency_key,body,async()=>{const current=read(),anchor=find(body.observation_id);if(current.revision!==body.expected_revision)throw new WorkspaceApiError(409,'workspace_revision_conflict');if(!anchor||anchor.observation.kind!=='verified_visit'||anchor.source_sha256!==body.observation_sha256||anchor.observation.item.handle!==body.item_handle||anchor.observation.item.sha256!==body.item_sha256)throw new WorkspaceApiError(409,'ehr_read_source_changed');
     const content=ehrSourceContent(anchor.observation),entry_id=crypto.randomUUID(),revision=current.revision+1;
     const workspace:Workspace={...current,revision,model_observed_at:new Date().toISOString(),entries:[...current.entries,{id:entry_id,revision,kind:'ehr_read_source',content,source_label:'Elation: reviewed appointment',origin:'authenticated_human',ticket:null,created_at:new Date().toISOString(),ehr_source_state:'current'}]};write(workspace);
     return {transport:'mock',entry_id,entry_revision:revision,request_sha256:await ehrReviewHash(current.id,body),source_withheld:false,workspace,source:{entry_id,source_sha256:await ehrSourceHash(anchor,anchor.observation.item),content_sha256:await ehrContentHash(content)}};
    });
    if(new URLSearchParams(location.search).get('scenario')==='ehr-lost-review'&&!lostReview){lostReview=true;throw new Error('Invented lost saved-source response');}
    return response(result);
   }
   if(body.action==='status')return response({contract_version:1,provider:'elation',mode:'synthetic',transport:'mock',installation:null,status:'ready',...binding,practice});
   if(body.action==='resolve'){stats.resolves++;return response(ledger.get(body.idempotency_key)?.value??{status:'not_found',observation_id:null,observation_key:body.idempotency_key});}
   if(body.action==='inspect'){stats.inspects++;const value=find(body.observation_id);if(!value)throw new WorkspaceApiError(409,'ehr_read_not_observed');return response(value);}
   if(!validEhrCommand(body)||body.connection_id!==binding.connection_id||body.binding_sha256!==binding.binding_sha256)throw new WorkspaceApiError(422,'invalid_ehr_read_request');
   return response(await retain(body.idempotency_key,body,async()=>{stats.reads++;
    if(body.action==='observe'){
     const duration=Date.parse(body.ends_at)-Date.parse(body.starts_at),starts=Date.parse(body.starts_at)+Math.min(3600000,duration/4);
     const item:EhrWindowItem={handle:crypto.randomUUID(),sha256:'',starts_at:new Date(starts).toISOString(),ends_at:new Date(starts+Math.min(1800000,duration/4)).toISOString(),status:'Scheduled',selectable:true};item.sha256=await ehrItemHash(item);
     const observation={kind:'window' as const,provider:'elation' as const,mode:'synthetic' as const,practice,observed_at:new Date().toISOString(),window:{starts_at:body.starts_at,ends_at:body.ends_at},coverage:'end_of_results' as const,items:[item]};
     return {contract_version:1,transport:'mock',...binding,observation_id:crypto.randomUUID(),observation_key:body.idempotency_key,source_sha256:await ehrHash({body,observation}),payload_sha256:await ehrHash(observation),observation};
    }
    const anchor=find(body.observation_id);if(!anchor||anchor.observation.kind!=='window')throw new WorkspaceApiError(409,'ehr_read_not_observed');const source=anchor.observation.items.find(item=>item.handle===body.item_handle);if(!source)throw new WorkspaceApiError(409,'ehr_read_source_changed');
    const {selectable:_,...fields}=source,item:EhrVerifiedItem={...fields,patient:{first_name:'Jordan',last_name:'Cypress',birth_date:'1990-03-04'}};item.sha256=await ehrItemHash(item);
    const {items:__,...base}=anchor.observation,observation={...base,kind:'verified_visit' as const,observed_at:new Date().toISOString(),item};
    const result:EhrReceipt={contract_version:1,transport:'mock',...binding,observation_id:crypto.randomUUID(),observation_key:body.idempotency_key,source_sha256:await ehrHash({body,observation}),payload_sha256:await ehrHash(observation),observation};
    if(!ehrMatchesCommand(result,body,anchor))throw new WorkspaceApiError(409,'ehr_read_source_changed');return result;
   }));
  }catch(error){if(error instanceof WorkspaceApiError)return response({detail:error.code??'invalid_ehr_read_request'},error.status);throw error;}
 };
}

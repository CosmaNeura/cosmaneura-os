import {teamCanonical,teamClosed as closed,teamHash,teamLiteral,teamNatural,teamStrip,teamText,teamUuid} from './team-setup-request';
import {modelTime} from './model-work-request';
import {validResearchAnchor,validResearchAnalysisDraft,type ResearchEvidenceAnchor,type ResearchAnalysisDraft} from './research-analysis-contract';

export const RESEARCH_SOURCES=['pubmed','clinical_trials','dailymed','rxnorm','openfda','cms_coverage','cms_open_data','medicare_care_compare','npi_registry'] as const;
export const RESEARCH_TOPICS=['literature','drug_safety','trials','coverage','provider_data'] as const;
export type ResearchSource=typeof RESEARCH_SOURCES[number];
export type ResearchTopic=typeof RESEARCH_TOPICS[number];
export const TOPIC_LABELS:Record<ResearchTopic,string>={literature:'Literature',drug_safety:'Drug warnings',trials:'Clinical trials',coverage:'Coverage versions',provider_data:'Provider data'};
export const RESEARCH_REQUEST_BYTES=8192,RESEARCH_RESPONSE_BYTES=131072,RESEARCH_HISTORY_BYTES=1048576,RESEARCH_DEADLINE_MS=35000;
export type ResearchCatalog={contract:'research.catalog.v1';enabled:boolean;sources:{id:ResearchSource;label:string;topics:ResearchTopic[];state:'enabled'|'not_configured';description:string;documentation_url:string}[];topics:{id:ResearchTopic;label:string}[]};
export type ResearchSearch={contract_version:1;idempotency_key:string;expected_revision:number;team_revision:number;bot:string;topic:ResearchTopic;sources:ResearchSource[];query:string;public_query_confirmed:true};
export type ResearchResult={source:ResearchSource;id:string;title:string;url:string;source_updated_at:string|null;version:string|null;retrieved_at:string;excerpt:string;truncated:boolean;raw_response_sha256:string;query_sha256:string;result_scope:"limited"|"complete"|"unknown";attribution:string;fields:{label:string;text:string}[];sha256:string};
export type ResearchObservation={contract:'research.lookup.v1';workspace_id:string;run_id:string;idempotency_key:string;request_sha256:string;request:ResearchSearch;bot:string;topic:ResearchTopic;query:string;sources:ResearchSource[];created_at:string;state:'running'|'completed'|'partial'|'unavailable'|'interrupted';results:ResearchResult[];errors:{source:ResearchSource;code:string}[]};
export type ResearchSave={contract_version:1;idempotency_key:string;expected_revision:number;source_hashes:string[]};
export type ResearchSaved={contract:'research.saved.v1';workspace_id:string;run_id:string;idempotency_key:string;request_sha256:string;request:ResearchSave;entry_id:string;entry_revision:number};
export type ResearchHistory={contract:'research.history.v1';runs:ResearchObservation[]};
export type ResearchSavedPacket={query:string;saved:ResearchSaved};
export type ResearchSavedHistory={contract:'research.saved_history.v1';workspace_id:string;bot:string;packets:ResearchSavedPacket[]};
export type ResearchPending={kind:'search';request:ResearchSearch}|{kind:'save';run_id:string;request:ResearchSave};
export type ResearchPrevious={request:ResearchSearch;outcome:'interrupted'|'not_found';observed_at:string};
export type ResearchDraft={version:1;bot:string;topic:ResearchTopic;query:string;sources:ResearchSource[];pending:ResearchPending|null;previous_request?:ResearchPrevious;saved_packet?:ResearchEvidenceAnchor;analysis_draft?:ResearchAnalysisDraft};
export class ResearchContractError extends Error{constructor(){super('The research response could not be verified.');}}
const fail=():never=>{throw new ResearchContractError();};
const bytes=(v:unknown)=>new TextEncoder().encode(JSON.stringify(v)).byteLength;
export const SOURCE_TOPICS:Record<ResearchSource,ResearchTopic[]>={pubmed:['literature'],clinical_trials:['trials'],dailymed:['drug_safety'],rxnorm:['drug_safety'],openfda:['drug_safety'],cms_coverage:['coverage'],cms_open_data:['coverage','provider_data'],medicare_care_compare:['provider_data'],npi_registry:['provider_data']};
const SOURCE_HOSTS:Record<ResearchSource,string>={pubmed:'pubmed.ncbi.nlm.nih.gov',clinical_trials:'clinicaltrials.gov',dailymed:'dailymed.nlm.nih.gov',rxnorm:'mor.nlm.nih.gov',openfda:'api.fda.gov',cms_coverage:'www.cms.gov',cms_open_data:'data.cms.gov',medicare_care_compare:'data.cms.gov',npi_registry:'npiregistry.cms.hhs.gov'};
const uuid4=(v:unknown):v is string=>teamUuid(v)&&v[14]==='4';
const researchKey=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9:_-]{8,100}$/.test(v);
const positive=(v:unknown)=>teamNatural(v)&&v>0;
const list=<T extends string>(v:unknown,allowed:readonly T[],min=0,max=allowed.length):v is T[]=>Array.isArray(v)&&v.length>=min&&v.length<=max&&v.every(x=>teamLiteral(x,allowed))&&new Set(v).size===v.length;
const text=(v:unknown,max:number,min=0)=>teamText(v,max,min)&&!/[\x00-\x08\x0b-\x1f\x7f]/.test(v);
export async function researchDigest(value:unknown):Promise<string>{const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(teamCanonical(value)));return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,'0')).join('');}
export function researchUrl(value:unknown):value is string{
 if(!teamText(value,2048,1)||/[\x00-\x20\x7f\\#]/.test(value)||[...value].some(char=>teamStrip(char)===''))return false;
 const authority=/^https:\/\/([^/?#@]+)\//.exec(value)?.[1];if(!authority)return false;
 try{const u=new URL(value);return u.host===authority&&!u.username&&!u.password&&!u.port&&!u.hash&&u.protocol==='https:'&&u.hostname.includes('.')&&!u.hostname.endsWith('.')&&!/^(?:\d|localhost$)/.test(u.hostname)&&u.origin!=='null';}catch{return false;}
}
export function validResearchSearch(v:unknown):v is ResearchSearch{return closed(v,'contract_version,idempotency_key,expected_revision,team_revision,bot,topic,sources,query,public_query_confirmed')&&v.contract_version===1&&researchKey(v.idempotency_key)&&positive(v.expected_revision)&&positive(v.team_revision)&&uuid4(v.bot)&&teamLiteral(v.topic,RESEARCH_TOPICS)&&list(v.sources,RESEARCH_SOURCES,1,3)&&v.sources.every(source=>SOURCE_TOPICS[source].includes(v.topic as ResearchTopic))&&text(v.query,500,1)&&typeof v.query==='string'&&!/[\x00-\x1f]/.test(v.query)&&typeof v.query==='string'&&teamStrip(v.query)===v.query&&v.public_query_confirmed===true&&bytes(v)<=RESEARCH_REQUEST_BYTES;}
export function validResearchSave(v:unknown):v is ResearchSave{return closed(v,'contract_version,idempotency_key,expected_revision,source_hashes')&&v.contract_version===1&&researchKey(v.idempotency_key)&&positive(v.expected_revision)&&Array.isArray(v.source_hashes)&&v.source_hashes.length>=1&&v.source_hashes.length<=5&&v.source_hashes.every(teamHash)&&new Set(v.source_hashes).size===v.source_hashes.length&&bytes(v)<=RESEARCH_REQUEST_BYTES;}
export function validateResearchCatalog(v:unknown):ResearchCatalog{
 if(!closed(v,'contract,enabled,sources,topics')||v.contract!=='research.catalog.v1'||typeof v.enabled!=='boolean'||!Array.isArray(v.sources)||v.sources.length>9||!Array.isArray(v.topics)||v.topics.length!==5)fail();
 const c=v as ResearchCatalog;
 if(c.sources.some(s=>!closed(s,'id,label,topics,state,description,documentation_url')||!teamLiteral(s.id,RESEARCH_SOURCES)||!text(s.label,100,1)||!list(s.topics,RESEARCH_TOPICS,1)||!teamLiteral(s.state,['enabled','not_configured'])||!text(s.description,1000)||!researchUrl(s.documentation_url))||new Set(c.sources.map(s=>s.id)).size!==c.sources.length||c.topics.some(t=>!closed(t,'id,label')||!teamLiteral(t.id,RESEARCH_TOPICS)||!text(t.label,100,1))||new Set(c.topics.map(t=>t.id)).size!==5||bytes(c)>RESEARCH_RESPONSE_BYTES)fail();return c;
}
export async function validateResearchObservation(v:unknown,workspace:string,expected?:ResearchSearch,bot?:string):Promise<ResearchObservation>{
 if(!closed(v,'contract,workspace_id,run_id,idempotency_key,request_sha256,request,bot,topic,query,sources,created_at,state,results,errors')||v.contract!=='research.lookup.v1'||v.workspace_id!==workspace||!teamUuid(v.run_id)||!teamHash(v.request_sha256)||!validResearchSearch(v.request)||!modelTime(v.created_at)||!teamLiteral(v.state,['running','completed','partial','unavailable','interrupted'])||!Array.isArray(v.results)||v.results.length>15||!Array.isArray(v.errors)||v.errors.length>3||bytes(v)>RESEARCH_RESPONSE_BYTES)fail();
 const o=v as ResearchObservation,r=o.request;
 if(o.idempotency_key!==r.idempotency_key||o.bot!==r.bot||o.topic!==r.topic||o.query!==r.query||teamCanonical(o.sources)!==teamCanonical(r.sources)||bot&&o.bot!==bot||expected&&teamCanonical(r)!==teamCanonical(expected)||o.request_sha256!==await researchDigest(r))fail();
 if((o.state==='running'||o.state==='interrupted')&&(o.results.length||o.errors.length)||o.state==='completed'&&o.errors.length||o.state==='partial'&&(!o.results.length||!o.errors.length)||o.state==='unavailable'&&(o.results.length||!o.errors.length))fail();
 const counts=new Map<string,number>(),hashes=new Set<string>(),identities=new Set<string>();
 for(const s of o.results){
  if(!closed(s,'source,id,title,url,source_updated_at,version,retrieved_at,excerpt,truncated,raw_response_sha256,query_sha256,result_scope,attribution,fields,sha256')||!r.sources.includes(s.source)||!text(s.id,128,1)||!text(s.title,500,1)||!researchUrl(s.url)||new URL(s.url).hostname!==SOURCE_HOSTS[s.source]||s.source_updated_at!==null&&(!text(s.source_updated_at,80,1)||!teamStrip(s.source_updated_at))||s.version!==null&&(!text(s.version,128,1)||!teamStrip(s.version))||!modelTime(s.retrieved_at)||!text(s.excerpt,2500)||typeof s.truncated!=='boolean'||!teamHash(s.raw_response_sha256)||!teamHash(s.query_sha256)||!teamLiteral(s.result_scope,['limited','complete','unknown'])||!text(s.attribution,200,1)||!Array.isArray(s.fields)||s.fields.length>12||s.fields.some(f=>!closed(f,'label,text')||!text(f.label,80,1)||!text(f.text,1500))||!teamHash(s.sha256)||hashes.has(s.sha256)||identities.has(JSON.stringify([s.source,s.id,s.version])))fail();
  const {sha256,...content}=s;if(sha256!==await researchDigest(content)||s.query_sha256!==await researchDigest({source:s.source,query:r.query}))fail();
  hashes.add(s.sha256);identities.add(JSON.stringify([s.source,s.id,s.version]));counts.set(s.source,(counts.get(s.source)??0)+1);if(counts.get(s.source)!>5)fail();
 }
 if(o.errors.some(e=>!closed(e,'source,code')||!r.sources.includes(e.source)||!teamLiteral(e.code,['source_unavailable','source_timeout','source_rate_limited','invalid_source_response','source_not_configured','no_matching_record']))||new Set(o.errors.map(e=>e.source)).size!==o.errors.length)fail();return o;
}
export async function validateResearchHistory(v:unknown,workspace:string,bot:string):Promise<ResearchHistory>{if(!closed(v,'contract,runs')||v.contract!=='research.history.v1'||!Array.isArray(v.runs)||v.runs.length>5||bytes(v)>RESEARCH_HISTORY_BYTES)fail();const h=v as ResearchHistory;for(const run of h.runs)await validateResearchObservation(run,workspace,undefined,bot);if(new Set(h.runs.map(r=>r.run_id)).size!==h.runs.length)fail();return h;}
export async function validateResearchSaved(v:unknown,workspace:string,run:string,expected:ResearchSave):Promise<ResearchSaved>{if(!closed(v,'contract,workspace_id,run_id,idempotency_key,request_sha256,request,entry_id,entry_revision')||v.contract!=='research.saved.v1'||v.workspace_id!==workspace||v.run_id!==run||!teamUuid(v.entry_id)||!positive(v.entry_revision)||Number(v.entry_revision)!==expected.expected_revision+1||!validResearchSave(v.request)||v.idempotency_key!==expected.idempotency_key||teamCanonical(v.request)!==teamCanonical(expected)||v.request_sha256!==await researchDigest(expected))fail();return v as ResearchSaved;}
export async function validateResearchSavedHistory(v:unknown,workspace:string,bot:string):Promise<ResearchSavedHistory>{
 if(!closed(v,'contract,workspace_id,bot,packets')||v.contract!=='research.saved_history.v1'||v.workspace_id!==workspace||v.bot!==bot||!Array.isArray(v.packets)||v.packets.length>5||bytes(v)>RESEARCH_RESPONSE_BYTES)fail();
 const history=v as ResearchSavedHistory;let previous=Infinity;
 for(const packet of history.packets){
  if(!closed(packet,'query,saved')||!text(packet.query,500,1)||!closed(packet.saved,'contract,workspace_id,run_id,idempotency_key,request_sha256,request,entry_id,entry_revision')||!teamUuid(packet.saved.run_id)||!validResearchSave(packet.saved.request))fail();
  await validateResearchSaved(packet.saved,workspace,packet.saved.run_id,packet.saved.request);
  if(packet.saved.entry_revision>=previous)fail();previous=packet.saved.entry_revision;
 }
 if(new Set(history.packets.map(packet=>packet.saved.entry_id)).size!==history.packets.length)fail();return history;
}
export function validateResearchDraft(v:unknown,bot:string):ResearchDraft{
 if(!closed(v,'version,bot,topic,query,sources,pending','previous_request,saved_packet,analysis_draft')||v.version!==1||v.bot!==bot||!teamUuid(bot)||!teamLiteral(v.topic,RESEARCH_TOPICS)||!text(v.query,500)||!list(v.sources,RESEARCH_SOURCES,0,3)||'saved_packet' in v&&!validResearchAnchor(v.saved_packet)||'analysis_draft' in v&&(!validResearchAnalysisDraft(v.analysis_draft)||!validResearchAnchor(v.saved_packet)))fail();
 const d=v as ResearchDraft,p=d.pending,previous=d.previous_request;
 if(previous!==undefined&&(!closed(previous,'request,outcome,observed_at')||!validResearchSearch(previous.request)||previous.request.bot!==bot||!teamLiteral(previous.outcome,['interrupted','not_found'])||!modelTime(previous.observed_at)))fail();
 if(p!==null){if(!closed(p,p.kind==='search'?'kind,request':'kind,run_id,request'))fail();if(p.kind==='search'){if(!validResearchSearch(p.request))fail();}else if(p.kind!=='save'||!teamUuid(p.run_id)||!validResearchSave(p.request))fail();}
 if(p?.kind==='search'&&(p.request.bot!==bot||p.request.query!==d.query||p.request.topic!==d.topic||teamCanonical(p.request.sources)!==teamCanonical(d.sources)))fail();return d;
}

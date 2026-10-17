import {workspaceApi,WorkspaceApiError,type Workspace,type ProviderTeam,type BotRole,type WorkspaceEntry} from '../src/workspace-api';
import {teamSetupApi} from '../src/team-setup-api';
import {policySetupFixture,resourcesFixture,usageFixture,policyRehearsalFixture} from '../src/team-policy-test-fixture';
import {modelReceipt,modelUuid} from '../src/model-work-test-fixture';
export const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
const roles:BotRole[]=['visit_prep','scribe','follow_up','chief'];
const names=['Visit Prep','Scribe','Follow-up','Chief of Staff'];
const stamp=new Date().toISOString();
const storageKey='cosmabot-desktop-ux-acceptance-v1';
let team:ProviderTeam={revision:1,recovery_scope:'a'.repeat(64),template_version:'provider-team-v1',
  llm:{enabled:true,model:'Synthetic scripted replies'},capture:{enabled:true,prep_enabled:true},
  configuration:{practice_context:'Synthetic family practice',bots:roles.map((role,i)=>({role,name:names[i],enabled:true,
    response_style:'brief',include_notebook:true,include_evidence:true}))},
  members:roles.map((role,i)=>({role,agent_id:modelUuid(100+i),name:names[i],initials:names[i].slice(0,2),
    description:['Prepare for the visit','Organize your visit note','Track work after the visit','Coordinate the team'][i],prompt:'Review saved synthetic context',
    capabilities:[{key:'core.session_prep.read',label:'Session Prep',state:'enabled',connector:'Core',contract:'core.session-prep.brief.v1'}]}))};
const drafts=[
  'Contact time conflicts: the intake says after 15:00; the derived summary says morning. Clarify with Jordan. Contact consent is undocumented.',
  'Provider discussed appointment access. Plan: staff should clarify contact preference and obtain the medication list. Completion is not documented. No patient message has been sent.',
  'Staff checklist: confirm contact preference and consent; obtain the medication list; record completion after each action. These actions are not documented as complete.',
];
const entry=(id:string,revision:number,kind:WorkspaceEntry['kind'],content:string):WorkspaceEntry=>({id,revision,kind,content,
  source_label:kind==='synthetic_source'?'Invented encounter input':null,origin:'synthetic_fixture',ticket:null,created_at:stamp});
function initial():Workspace{
  const chief=entry(modelUuid(600),2,'conversation','Please prepare the saved intake and visit notes for handoffs.');
  chief.reply={agent_name:'Chief of Staff',agent_id:modelUuid(103),role:'chief',backend:'azure_gpt41',
    content:'Three private drafts are ready for your review. Contact preference, consent and the medication list still need staff attention.',context_revision:1,citations:[]};
  return {notebook:{title:'Jordan · sleep diary follow-up',title_revision:0,created_at:stamp},id:modelUuid(71),appointment_id:modelUuid(72),label:'Jordan Cypress · synthetic visit',revision:5,work_candidates:[],follow_ups:[],
    entries:[entry(modelUuid(1),1,'synthetic_source','Invented intake: appointment access concern, after-15:00 contact preference, medication list missing, consent undocumented.'),chief,
      ...drafts.map((body,i)=>({...entry(modelUuid(610+i),3+i,'handoff_result','Private draft result'),reply:{agent_name:names[i],agent_id:modelUuid(100+i),
        role:roles[i],backend:'azure_gpt41',content:body,context_revision:2,citations:[]}}))],
    handoffs:drafts.map((_,i)=>({id:modelUuid(700+i),origin_entry_id:chief.id,recipient_role:roles[i] as 'visit_prep'|'scribe'|'follow_up',
      recipient_name:names[i],recipient_agent_id:modelUuid(100+i),brief:['Summarize the conflicting contact preferences.','Draft the documented discussion and planned actions.','Prepare a staff checklist for the outstanding actions.'][i],
      context_revision:2,status:'completed',attempt_id:modelUuid(800+i),attempt_count:1,result_entry_id:modelUuid(610+i),error_code:null,
      attempts:[{id:modelUuid(800+i),number:1,status:'completed',error_code:null}]})),note:{latest:null,history:[]}};
}
let state:Workspace=JSON.parse(sessionStorage.getItem(storageKey)??'null')??initial();
const saved=new Map<string,unknown>();
const copy=()=>structuredClone(state);
const hash=async(text:string)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),b=>b.toString(16).padStart(2,'0')).join('');
function check(id:string,expected?:number){if(id!==state.id||expected!==undefined&&expected!==state.revision)throw new WorkspaceApiError(409);}
function persist(){sessionStorage.setItem(storageKey,JSON.stringify(state));}
function receipt(){persist();return {entry_revision:state.revision,workspace:copy()};}
async function once<T>(key:string,work:()=>Promise<T>):Promise<T>{if(saved.has(key))return structuredClone(saved.get(key)) as T;const result=await work();saved.set(key,result);return structuredClone(result);}
export function installFixtures(){
  Object.assign(teamSetupApi,{read:async()=>({...await policySetupFixture(team.configuration),team:structuredClone(team)}),resources:async()=>structuredClone(resourcesFixture),usage:async()=>structuredClone(usageFixture),rehearse:async(_identity:unknown,body:Parameters<typeof teamSetupApi.rehearse>[1])=>policyRehearsalFixture(body.configuration,body.expected_revision)});
  // The page is intentionally disconnected: unsupported service actions fail.
  window.fetch=async()=>{throw new Error('Service operation unavailable in this isolated UI fixture');};
  for(const key of Object.keys(workspaceApi) as (keyof typeof workspaceApi)[])Object.assign(workspaceApi,{[key]:async()=>{throw new WorkspaceApiError(503);}});
  Object.assign(workspaceApi,{
    catalog:async()=>[{appointment_id:state.appointment_id!,label:state.label,workspace_id:state.id,start_at:new Date().toISOString(),source:'synthetic_fixture'}],
    privateDraftSummaries:async()=>({contract_version:2,drafts:[{workspace_id:state.id,title:state.notebook?.title??'Jordan · sleep diary follow-up',title_revision:state.notebook?.title_revision??0,revision:state.revision,created_at:stamp,updated_at:stamp,link_state:state.appointment_id?'linked':'unlinked',appointment_id:state.appointment_id,patient_label:state.appointment_id?'Jordan Cypress':null,visit_at:state.appointment_id?new Date().toISOString():null,note_state:state.note?.latest?.review?'reviewed':state.note?.latest?'needs_review':'draft',duration_seconds:null,recording_state:'none'}],has_more:false}),
    createPrivateDraft:async(_identity:unknown,body:Parameters<typeof workspaceApi.createPrivateDraft>[1])=>{state=initial();state.id=crypto.randomUUID();state.appointment_id=null;state.label=body.title;state.notebook={title:body.title,title_revision:0,created_at:new Date().toISOString()};state.private_draft={state:'unlinked',title:body.title,created_at:new Date().toISOString()};state.entries=[];state.handoffs=[];state.revision=1;persist();return {identity,workspace:copy(),team:structuredClone(team)};},
    openPrivateDraft:async()=>({identity,workspace:copy(),team:structuredClone(team)}),
    saveTeam:async(_identity:unknown,body:Parameters<typeof workspaceApi.saveTeam>[1])=>{team={...team,revision:team.revision+1,configuration:structuredClone(body.configuration)};return structuredClone(team);},
    renameNotebook:async(_identity:unknown,id:string,body:Parameters<typeof workspaceApi.renameNotebook>[2])=>{check(id);state.notebook={title:body.title,title_revision:(state.notebook?.title_revision??0)+1,created_at:state.notebook?.created_at??stamp};persist();return {contract_version:1,workspace_id:id,title:body.title,title_revision:state.notebook.title_revision,receipt_id:crypto.randomUUID()};},
    team:async()=>structuredClone(team),
    open:async()=>({identity,workspace:copy(),team:structuredClone(team)}),
    openExisting:async()=>({identity,workspace:copy(),team:structuredClone(team)}),
    read:async(_identity:unknown,id:string)=>{check(id);return copy();},
    append:async(_identity:unknown,id:string,body:Parameters<typeof workspaceApi.append>[2])=>once(body.idempotency_key,async()=>{
      check(id,body.expected_revision);const added=entry(crypto.randomUUID(),++state.revision,body.kind,body.content);added.source_label=body.source_label??null;
      state.entries.push(added);return {entry_id:added.id,...receipt()};}),
    saveNote:async(_identity:unknown,id:string,body:Parameters<typeof workspaceApi.saveNote>[2])=>once(body.idempotency_key,async()=>{
      check(id,body.expected_revision);if(body.base_note_id!==(state.note?.latest?.id??null))throw new WorkspaceApiError(409);
      const note={id:crypto.randomUUID(),version:(state.note?.history.length??0)+1,workspace_revision:++state.revision,content:body.content,
        content_hash:await hash(body.content),source_reply_id:body.source_reply_id,source_revision:state.revision,source_fingerprint:'f'.repeat(64),
        sources_changed:false,created_at:new Date().toISOString(),review:null};
      state.note={latest:note,history:[...(state.note?.history??[]),note]};return receipt();}),
    reviewNote:async(_identity:unknown,id:string,noteId:string,body:Parameters<typeof workspaceApi.reviewNote>[3])=>once(body.idempotency_key,async()=>{
      check(id,body.expected_revision);const note=state.note?.latest;
      if(!note||note.id!==noteId||note.content_hash!==body.content_hash||note.source_fingerprint!==body.source_fingerprint)throw new WorkspaceApiError(409);
      note.review={id:crypto.randomUUID(),reviewer_id:'synthetic-tester',created_at:new Date().toISOString()};
      state.note!.history=state.note!.history.map(item=>item.id===note.id?structuredClone(note):item);state.revision++;return receipt();}),
    ask:async(_identity:unknown,id:string,body:Parameters<typeof workspaceApi.ask>[2])=>once(body.idempotency_key,async()=>{
      check(id,body.expected_revision);const added=entry(modelUuid(601),++state.revision,'conversation',body.content);
      added.id=crypto.randomUUID();const i=roles.indexOf(body.role as BotRole);
      added.reply={agent_name:names[i]??'Chief of Staff',role:roles[i]??'chief',backend:'azure_gpt41',context_revision:body.expected_revision,citations:[],
        content:`Scripted usability fixture response: ${drafts[i]??'The three saved drafts remain available. Staff action completion is not documented.'}`};
      state.entries.push(added);persist();const result=await modelReceipt(body,id,state.revision);result.saved_entry={id:added.id,revision:state.revision};return result;}),
    practiceWork:async()=>({items:[],people:[],next_cursor:null}),
  } satisfies Partial<typeof workspaceApi>);
}

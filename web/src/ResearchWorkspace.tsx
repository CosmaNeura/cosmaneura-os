import {useEffect,useRef,useState} from 'react';
import {researchApi,type ResearchPort} from './research-api';
import {RESEARCH_TOPICS,TOPIC_LABELS,validResearchSearch,validateResearchCatalog,validateResearchDraft,validateResearchHistory,validateResearchObservation,validateResearchSaved,type ResearchPrevious,type ResearchCatalog,type ResearchDraft,type ResearchObservation,type ResearchPending,type ResearchResult,type ResearchSearch,type ResearchSource} from './research-contract';
import {editorDraft,EditorRecoveryNotice,useEditorRecovery} from './editor-recovery';
import {useUnsavedWork} from './unsaved-work';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type ConversationInput} from './workspace-api';
import {ResearchAnalysisPanel,type ResearchAnalysisAccess} from './ResearchAnalysisPanel';
import {validConversation} from './model-work-request';
import {teamStrip} from './team-setup-request';
import type {EditorDraft} from './draft-journal';
import {validateResearchSavedHistory,type ResearchSavedPacket} from './research-contract';
import './research-workspace.css';

const blank=(bot:string):ResearchDraft=>({version:1,bot,topic:'literature',query:'',sources:[],pending:null});
const stateLabel:Record<ResearchObservation['state'],string>={running:'Lookup in progress',completed:'Sources retrieved',partial:'Some sources unavailable',unavailable:'Sources unavailable',interrupted:'Lookup interrupted — outcome unconfirmed'};
const sourceLabel=(source:ResearchSource,catalog:ResearchCatalog|null)=>catalog?.sources.find(s=>s.id===source)?.label??source.replaceAll('_',' ');
export function ResearchWorkspace({identity,workspaceId,workspaceRevision,bot,enabled,locked,onDenied,onChanged,analysis,port=researchApi}: {
 identity:AuthenticatedWorkspaceIdentity;workspaceId:string;workspaceRevision:number;bot:{address:string;team_revision:number};enabled:boolean;locked:boolean;
 onDenied?:(cause:WorkspaceApiError)=>void;onChanged?:(revision:number)=>void;analysis?:ResearchAnalysisAccess;port?:ResearchPort;
}){
 const [draft,setDraft]=useState<ResearchDraft>(()=>blank(bot.address)),[catalog,setCatalog]=useState<ResearchCatalog|null>(null),[catalogError,setCatalogError]=useState(false);
 const [review,setReview]=useState<ResearchSearch|null>(null),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 const [observation,setObservation]=useState<ResearchObservation|null>(null),[selected,setSelected]=useState<string[]>([]),[history,setHistory]=useState<ResearchObservation[]>([]);
 const [historyMore,setHistoryMore]=useState(false),[packets,setPackets]=useState<ResearchSavedPacket[]>([]),[packetsMore,setPacketsMore]=useState(false);
 const [replacement,setReplacement]=useState<ResearchPrevious|null>(null),[replaceAcknowledged,setReplaceAcknowledged]=useState(false),[previousResult,setPreviousResult]=useState<ResearchObservation|null>(null);
 const [showSavedChat,setShowSavedChat]=useState(false); // Reserved only for the focused view's explanation; no query forwarding.
 const catalogRequest=useRef<AbortController|null>(null);
 const inFlight=useRef(false),operation=useRef<AbortController|null>(null),generation=useRef(0);
 const live=useRef({identity,workspaceId,bot,enabled,locked,analysis});live.current={identity,workspaceId,bot,enabled,locked,analysis};
 const kind=`research:${bot.address}` as const;
 const value=draft.query||draft.sources.length||draft.pending||draft.previous_request||draft.saved_packet||draft.analysis_draft?editorDraft(workspaceId,kind,draft,draft.pending?.request.idempotency_key??null):null;
 const recovery=useEditorRecovery(workspaceId,kind,value,busy,{required:true,identity,scopeKey:bot.address});
 const blocked=locked||busy||recovery.blocked,canSearch=enabled&&!blocked&&!draft.pending;
 useUnsavedWork(!!draft.pending||!!draft.query||!!draft.analysis_draft?.question||busy);
 useEffect(()=>{generation.current++;return()=>{generation.current++;operation.current?.abort();};},[identity,workspaceId,bot.address]);
 useEffect(()=>{setReview(null);setConfirmed(false);},[workspaceRevision,bot.team_revision,enabled,locked]);
 function current(n:number,controller:AbortController){return n===generation.current&&!controller.signal.aborted&&live.current.identity===identity&&live.current.workspaceId===workspaceId&&live.current.bot.address===bot.address;}
 function denied(cause:unknown){if(cause instanceof WorkspaceApiError&&[401,403].includes(cause.status))onDenied?.(cause);}
 async function loadCatalog(){
  const n=generation.current,controller=new AbortController();catalogRequest.current?.abort();catalogRequest.current=controller;setCatalogError(false);
  try{const value=validateResearchCatalog(await port.catalog(identity,controller.signal));if(current(n,controller))setCatalog(value);}
  catch(cause){if(current(n,controller)){setCatalog(null);setCatalogError(true);denied(cause);}}
  if(catalogRequest.current===controller)catalogRequest.current=null;
 }
 useEffect(()=>{void loadCatalog();return()=>catalogRequest.current?.abort();},[identity,workspaceId,bot.address,port]);
 function edit(update:Partial<ResearchDraft>){if(!canSearch)return;setDraft(d=>({...d,...update}));setReview(null);setConfirmed(false);setMessage('');}
 const sources=catalog?.sources.filter(s=>s.topics.includes(draft.topic))??[];
 const selectedAvailable=!!catalog?.enabled&&draft.sources.length>0&&draft.sources.every(id=>sources.some(s=>s.id===id&&s.state==='enabled'));
 function reviewQuery(){if(!canSearch||!selectedAvailable||!teamStrip(draft.query))return;const query=teamStrip(draft.query);setDraft(d=>({...d,query}));const request={contract_version:1 as const,idempotency_key:crypto.randomUUID(),expected_revision:workspaceRevision,team_revision:bot.team_revision,bot:bot.address,topic:draft.topic,sources:[...draft.sources],query,public_query_confirmed:true as const};if(!validResearchSearch(request)){setMessage('Use one general question without line breaks or control characters.');return;}setReview(request);setConfirmed(false);}
 function snapshot(next:ResearchDraft):EditorDraft{return editorDraft(workspaceId,kind,next,next.pending?.request.idempotency_key??null);}
 async function execute(pending:ResearchPending,resolve=false){
  if(inFlight.current||blocked||!resolve&&(!enabled||draft.pending))return;
  inFlight.current=true;setBusy(true);setMessage('');setReview(null);setConfirmed(false);
  const controller=new AbortController(),n=generation.current;operation.current=controller;
  const retained={...draft,pending};
  try{
   // The exact intent is durable before any public lookup or internal evidence save.
   await recovery.commit(snapshot(retained));if(!current(n,controller))return;setDraft(retained);if(!resolve&&!live.current.enabled||live.current.locked)return;
   if(pending.kind==='search'){
    const raw=await (resolve?port.resolve:port.search)(identity,workspaceId,pending.request,controller.signal);
    const result=await validateResearchObservation(raw,workspaceId,pending.request,bot.address);if(!current(n,controller))return;
    const unsettled=result.state==='running'||result.state==='interrupted',next={...retained,pending:unsettled?pending:null};
    await recovery.commit(snapshot(next));if(!current(n,controller))return;setDraft(next);setObservation(result);setSelected([]);if(result.state==='interrupted'){setReplacement({request:pending.request,outcome:'interrupted',observed_at:new Date().toISOString()});setReplaceAcknowledged(false);}else setReplacement(null);setMessage(unsettled?'The request is retained. Check its saved result before starting another lookup.':'Source excerpts are ready to compare. They have not been added to your encounter.');
   }else{
    const raw=await (resolve?port.resolveSave:port.save)(identity,workspaceId,pending.run_id,pending.request,controller.signal);
    const result=await validateResearchSaved(raw,workspaceId,pending.run_id,pending.request);if(!current(n,controller))return;
    const next={...retained,pending:null,saved_packet:{entry_id:result.entry_id,entry_revision:result.entry_revision,run_id:result.run_id,save_request_sha256:result.request_sha256},analysis_draft:{question:retained.analysis_draft?.question??'',selected:false}};await recovery.commit(snapshot(next));if(!current(n,controller))return;setDraft(next);setSelected([]);setMessage(`Selected excerpts saved as encounter evidence · revision ${result.entry_revision}. Clinical review and any follow-up remain separate.`);onChanged?.(result.entry_revision);
   }
  }catch(cause){if(current(n,controller)){setDraft(retained);if(resolve&&pending.kind==='search'&&cause instanceof WorkspaceApiError&&cause.code==='research_not_found'){setReplacement({request:pending.request,outcome:'not_found',observed_at:new Date().toISOString()});setReplaceAcknowledged(false);}setMessage(resolve?'A saved result could not be confirmed. The exact request remains on this device; checking does not resend it.':'The result could not be confirmed. The exact request is retained; check its saved result before continuing.');denied(cause);}}
  finally{if(current(n,controller)){inFlight.current=false;setBusy(false);}if(operation.current===controller)operation.current=null;}
 }
 async function replaceSearch(){
  if(blocked||!enabled||!replaceAcknowledged||!replacement||draft.pending?.kind!=='search'||replacement.request.idempotency_key!==draft.pending.request.idempotency_key)return;
  const next={...draft,query:'',pending:null,previous_request:replacement};const controller=new AbortController(),n=generation.current;inFlight.current=true;setBusy(true);
  try{await recovery.commit(snapshot(next));if(current(n,controller)){setDraft(next);setReplacement(null);setReplaceAcknowledged(false);setReview(null);setConfirmed(false);setMessage('Previous request retained. Write and review a new question; nothing has been sent.');}}
  catch{if(current(n,controller))setMessage('The prior request could not be retained safely. Existing work is unchanged.');}
  finally{if(current(n,controller)){setBusy(false);inFlight.current=false;}}
 }
 async function checkPrevious(){
  if(blocked||inFlight.current||!draft.previous_request)return;const prior=draft.previous_request;inFlight.current=true;setBusy(true);const controller=new AbortController(),n=generation.current;operation.current=controller;
  try{const result=await validateResearchObservation(await port.resolve(identity,workspaceId,prior.request,controller.signal),workspaceId,prior.request,bot.address);if(current(n,controller))setPreviousResult(result);}
  catch(cause){if(current(n,controller)){setMessage('The previous result could not be confirmed. Its exact request is still retained.');denied(cause);}}
  finally{if(current(n,controller)){setBusy(false);inFlight.current=false;}if(operation.current===controller)operation.current=null;}
 }
 async function loadHistory(before?:string){
  if(blocked||inFlight.current)return;inFlight.current=true;setBusy(true);setMessage('');const controller=new AbortController(),n=generation.current;operation.current=controller;
  try{
   const result=await validateResearchHistory(await port.history(identity,workspaceId,bot.address,controller.signal,before),workspaceId,bot.address);
   if(current(n,controller)){
    const next=before?[...history,...result.runs]:result.runs;
    if(next.length>100||new Set(next.map(run=>run.run_id)).size!==next.length)throw new Error('Invalid research history page');
    setHistory(next);setHistoryMore(result.runs.length===5);
   }
  }
  catch(cause){if(current(n,controller)){setMessage('Saved research history could not be confirmed. Your current question and requests remain available.');denied(cause);}}
  finally{if(current(n,controller)){setBusy(false);inFlight.current=false;}if(operation.current===controller)operation.current=null;}
 }
 async function loadPackets(before?:string){
  if(blocked||inFlight.current)return;inFlight.current=true;setBusy(true);setMessage('');const controller=new AbortController(),n=generation.current;operation.current=controller;
  try{
   const result=await validateResearchSavedHistory(await port.savedHistory(identity,workspaceId,bot.address,controller.signal,before),workspaceId,bot.address);
   if(current(n,controller)){
    const next=before?[...packets,...result.packets]:result.packets;
    if(next.length>500||new Set(next.map(packet=>packet.saved.entry_id)).size!==next.length||next.some((packet,index)=>index>0&&packet.saved.entry_revision>=next[index-1].saved.entry_revision))throw new Error('Invalid saved packet page');
    setPackets(next);setPacketsMore(result.packets.length===5);
   }
  }catch(cause){if(current(n,controller)){setMessage('Saved source packets could not be confirmed. Your question and current selection remain available.');denied(cause);}}
  finally{if(current(n,controller)){setBusy(false);inFlight.current=false;}if(operation.current===controller)operation.current=null;}
 }
 function selectPacket(packet:ResearchSavedPacket){
  if(blocked||draft.pending)return;
  const saved=packet.saved;
  setDraft(value=>({...value,saved_packet:{entry_id:saved.entry_id,entry_revision:saved.entry_revision,run_id:saved.run_id,save_request_sha256:saved.request_sha256},analysis_draft:{question:value.analysis_draft?.question??'',selected:false}}));
  setMessage('Saved packet selected. Review the exact packet and confirm it before requesting analysis.');
 }
 function saveSelected(){if(!canSearch||!observation||!selected.length||selected.length>5)return;void execute({kind:'save',run_id:observation.run_id,request:{contract_version:1,idempotency_key:crypto.randomUUID(),expected_revision:workspaceRevision,source_hashes:[...selected]}});}
 async function submitAnalysis(body:ConversationInput){
  if(inFlight.current||blocked||draft.pending||!enabled||!analysis?.model.enabled||analysis.modelBlocked||!draft.saved_packet||!validConversation(body)||body.role!==bot.address||body.expected_revision!==workspaceRevision||body.team_revision!==bot.team_revision||JSON.stringify(body.research_analysis?.entries)!==JSON.stringify([draft.saved_packet]))return;
  const controller=new AbortController(),n=generation.current,model=JSON.stringify(analysis.model);operation.current=controller;inFlight.current=true;setBusy(true);setMessage('');
  try{
   await recovery.commit(snapshot(draft));
   if(!current(n,controller)||!live.current.enabled||live.current.locked||live.current.bot.team_revision!==body.team_revision||live.current.analysis?.workspace.id!==workspaceId||live.current.analysis.workspace.revision!==body.expected_revision||live.current.analysis.modelBlocked||JSON.stringify(live.current.analysis.model)!==model)return;
   await analysis.onSubmit(body);
  }catch(cause){if(current(n,controller)){setMessage('The analysis handoff could not be confirmed. Check the retained model request before sending again.');denied(cause);}}
  finally{if(current(n,controller)){inFlight.current=false;setBusy(false);}if(operation.current===controller)operation.current=null;}
 }
 const privateClient=identity.mode==='desktop_native'||!!identity.nativeSession;
 function resultCard(result:ResearchResult){return <article className="research-result" key={result.sha256}>
  <header><span className="research-badge">Source excerpt</span><span>{sourceLabel(result.source,catalog)}</span></header>
  <h3>{result.title}</h3><dl className="research-dates"><div><dt>Source date</dt><dd>{result.source_updated_at??'Not supplied'}</dd></div><div><dt>Version</dt><dd>{result.version??'Not supplied'}</dd></div><div><dt>Retrieved</dt><dd><time dateTime={result.retrieved_at}>{result.retrieved_at}</time></dd></div></dl>
  {result.result_scope!=='complete'&&<p className="team-fine">{result.result_scope==='limited'?'Limited result set; this is not an exhaustive search.':'Result coverage is not confirmed.'}</p>}
  <p className="research-excerpt">{result.excerpt||'This source returned metadata only; no excerpt was supplied.'}</p>
  {result.truncated&&<p className="team-fine">Excerpt shortened. Check the full source before applying criteria or warnings.</p>}
  <details><summary>Source details & citation</summary>{result.fields.map((field,index)=><div className="research-field" key={index}><strong>{field.label}</strong><p>{field.text}</p></div>)}
   <p>{privateClient?<span className="research-url">{result.url}</span>:<a href={result.url} target="_blank" rel="noreferrer noopener" referrerPolicy="no-referrer">Open source <span className="research-url">{result.url}</span></a>}</p>
   {privateClient&&<p className="team-fine">Source address shown. Opening external research sites from this app is not connected.</p>}
   <p className="team-fine">{result.attribution||"Attribution not supplied"}</p><small>Response fingerprint <span className="research-hash">{result.raw_response_sha256}</span></small><small>Query fingerprint <span className="research-hash">{result.query_sha256}</span></small>
   <small>Record {result.id} · <span className="research-hash">{result.sha256}</span></small>
  </details>
  <label className="research-select"><input type="checkbox" checked={selected.includes(result.sha256)} disabled={!canSearch||!selected.includes(result.sha256)&&selected.length>=5} onChange={event=>setSelected(current=>event.target.checked?[...current,result.sha256]:current.filter(h=>h!==result.sha256))}/>Select excerpt to save</label>
 </article>;}
 return <section className="research-workspace" aria-label="Research workspace">
  <header><p className="team-kicker">RESEARCH</p><h2>Find a source. Check the details.</h2><p>Review public literature, warnings, trial criteria and coverage versions alongside your own judgment.</p></header>
  <EditorRecoveryNotice recovery={recovery} label="Research" onRestore={async(saved,_workspace,isCurrent)=>{const next=validateResearchDraft(saved.data,bot.address);if(isCurrent()){setDraft(next);setReview(null);setConfirmed(false);setObservation(null);setSelected([]);}}}/>
  {!enabled&&<p className="research-status" role="status">Research is paused or not yet saved to your team. Saved work is retained.</p>}
  {!catalog?.enabled&&<div className="research-status" role="status"><strong>{catalogError?'Research connection could not be checked':'Public research is not connected'}</strong><p>Source availability does not confirm a working Cosmas connection. You can keep a question here while the connection is being prepared.</p><button disabled={blocked} onClick={()=>void loadCatalog()}>Check connection</button></div>}
  <form onSubmit={event=>{event.preventDefault();reviewQuery();}}>
   <fieldset disabled={!canSearch}><legend className="team-sr-only">Public research question</legend>
    <div className="research-topic-row">{RESEARCH_TOPICS.slice(0,4).map(topic=><button key={topic} type="button" aria-pressed={draft.topic===topic} onClick={()=>edit({topic,sources:[]})}>{TOPIC_LABELS[topic]}</button>)}</div>
    <details className="research-provider-topic"><summary>Provider information</summary><button type="button" aria-pressed={draft.topic==='provider_data'} onClick={()=>edit({topic:'provider_data',sources:[]})}>Provider data</button></details>
    <label className="research-question">Public question<textarea rows={3} maxLength={500} value={draft.query} onChange={event=>edit({query:event.target.value})} placeholder="For example, recent reviews of treatment options…"/></label>
    <p className="team-fine">Write a general question without patient identifiers. Your encounter, notebook and private conversation are not automatically included.</p>
    <details className="research-source-picker"><summary>{draft.sources.length ? `Sources · ${draft.sources.length} selected` : "Choose sources to continue"}</summary>{sources.length?sources.map(source=><label key={source.id}><input type="checkbox" disabled={source.state!=='enabled'||!draft.sources.includes(source.id)&&draft.sources.length>=3} checked={draft.sources.includes(source.id)} onChange={event=>edit({sources:event.target.checked?[...draft.sources,source.id]:draft.sources.filter(id=>id!==source.id)})}/><span>{source.label}<small>{source.state==='enabled'?'Connection configured':'Not connected'}</small></span></label>):<p>No source connection is confirmed for this topic.</p>}</details>
    <button className="team-primary" disabled={!selectedAvailable||!teamStrip(draft.query)}>Review query</button>
   </fieldset>
  </form>
  {review&&<section className="research-query-review" aria-label="Review public query"><h3>Check what will be sent</h3><p>{review.query}</p><p>To: {review.sources.map(id=>sourceLabel(id,catalog)).join(', ')}</p><label><input type="checkbox" checked={confirmed} disabled={blocked} onChange={event=>setConfirmed(event.target.checked)}/>This is a general public question, with no patient identifiers.</label><div><button disabled={blocked} onClick={()=>{setReview(null);setConfirmed(false);}}>Edit query</button><button className="team-primary" disabled={!confirmed||!canSearch||!selectedAvailable} onClick={()=>{if(confirmed&&canSearch&&selectedAvailable&&review.expected_revision===workspaceRevision&&review.team_revision===bot.team_revision)void execute({kind:'search',request:review});}}>Search selected sources</button></div></section>}
  {draft.pending&&<section className="research-status" aria-label="Unconfirmed research request"><strong>{draft.pending.kind==='search'?'Research request retained':'Evidence save retained'}</strong><p>Check the saved result. This does not start another lookup or save.</p><button disabled={blocked} onClick={()=>draft.pending&&void execute(draft.pending,true)}>Check saved result</button></section>}
  {replacement&&draft.pending?.kind==='search'&&<section className="research-status" aria-label="Prepare replacement search"><p>The previous request is retained and may still finish. A new search is a separate public lookup.</p><label><input type="checkbox" checked={replaceAcknowledged} disabled={blocked} onChange={event=>setReplaceAcknowledged(event.target.checked)}/>I understand the previous request may still finish.</label><button disabled={blocked||!enabled||!replaceAcknowledged} onClick={()=>void replaceSearch()}>Start a new search</button></section>}
  {draft.previous_request&&<details className="research-history"><summary>Previous request retained</summary><p>{draft.previous_request.request.query}</p><p className="team-fine">Its outcome was {draft.previous_request.outcome==='not_found'?'not found when checked':'interrupted when checked'}. This does not confirm that a prior upstream request stopped.</p><button disabled={blocked} onClick={()=>void checkPrevious()}>Check previous result</button>{previousResult&&<><p>{stateLabel[previousResult.state]}</p><ul>{previousResult.results.map(result=><li key={result.sha256}>{result.title}</li>)}</ul></>}</details>}
  {busy&&<p role="status">Checking research…</p>}{message&&<p role="status" className="research-status">{message}</p>}
  {analysis&&draft.saved_packet&&<ResearchAnalysisPanel access={analysis} packet={draft.saved_packet} draft={draft.analysis_draft??{question:'',selected:false}}
   bot={bot.address} teamRevision={bot.team_revision} enabled={enabled} locked={blocked||!!draft.pending}
   onEdit={next=>{if(!blocked&&!draft.pending)setDraft(value=>({...value,analysis_draft:next}));}} onSubmit={submitAnalysis}
   onSmaller={()=>{setSelected([]);setMessage('Choose fewer excerpts from the lookup below, or open saved research history first. Save the smaller selection as a new packet before requesting analysis.');}}/>}
  {observation&&<section className="research-results" aria-label="Research results"><header><h3>{stateLabel[observation.state]}</h3><p>{observation.query}</p><p className="team-fine">Retrieved records are source evidence. No AI synthesis or clinical inference is supplied by this lookup.</p></header>
   {!observation.results.length&&<p>No source records were confirmed for this lookup. This does not prove that evidence, warnings, trials or coverage are absent.</p>}
   {observation.errors.map(error=><p className="research-status" key={error.source}>{sourceLabel(error.source,catalog)} could not be confirmed for this lookup.</p>)}
   <div className="research-result-grid">{observation.results.map(resultCard)}</div>
   {!!observation.results.length&&<footer><span>{selected.length} of up to 5 selected</span><button className="team-primary" disabled={!canSearch||!selected.length} onClick={saveSelected}>Save selected excerpts</button></footer>}
  </section>}
  <details className="research-history"><summary>Saved research history</summary><button disabled={blocked} onClick={()=>void loadHistory()}>Load saved research</button>{history.map(run=><button key={run.run_id} disabled={blocked||!!draft.pending} onClick={()=>{setObservation(run);setSelected([]);}}><strong>{run.query}</strong><small>{stateLabel[run.state]} · {run.created_at}</small></button>)}{historyMore&&<button disabled={blocked} onClick={()=>void loadHistory(history[history.length-1]?.run_id)}>Load older lookups</button>}</details>
  {analysis&&<details className="research-history"><summary>Saved source packets</summary><p>Choose an existing packet for analysis. This does not repeat its lookup or save another copy.</p><button disabled={blocked} onClick={()=>void loadPackets()}>Load saved packets</button>{packets.map(packet=><button key={packet.saved.entry_id} disabled={blocked||!!draft.pending} onClick={()=>selectPacket(packet)}><strong>{packet.query}</strong><small>Saved packet · revision {packet.saved.entry_revision}</small></button>)}{packetsMore&&<button disabled={blocked} onClick={()=>void loadPackets(packets[packets.length-1]?.saved.entry_id)}>Load older packets</button>}</details>}
  <button type="button" className="team-subtle research-context-explanation" aria-expanded={showSavedChat} onClick={()=>setShowSavedChat(v=>!v)}>How this relates to my encounter</button>
  {showSavedChat&&<p className="team-fine">The saved encounter conversation uses this bot's separate context settings. Public research uses only the question and sources reviewed above. Saving an excerpt adds it to private encounter evidence for later review; it does not authorize treatment, coverage, or follow-up.</p>}
 </section>;
}

import {useEffect,useId,useMemo,useRef,useState} from 'react';
import {BotAvatar} from './BotAvatar';
import {coreConnectionApi} from './core-connection-api';
import {readVisitPrep} from './visit-prep-api';
import type {BriefItem,Topic,VisitPrepReceipt} from './visit-prep-contract';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

export function VisitPrepPackagePanel({identity,locked,onAccessLost}:{identity:AuthenticatedWorkspaceIdentity;locked:boolean;
  onAccessLost?:(error:WorkspaceApiError)=>void}){
  const [reference,setReference]=useState(''),[value,setValue]=useState<VisitPrepReceipt|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const scope=useMemo(()=>Symbol(),[identity,locked]),current=useRef(scope);current.current=scope;
  const active=useRef<AbortController|null>(null),visible=useRef(true),sourcePrefix=useId();
  const [owner,setOwner]=useState(scope);
  const clear=()=>{active.current?.abort();active.current=null;setValue(null);setBusy(false);setError('');};
  useEffect(()=>{clear();setOwner(scope);return()=>active.current?.abort();},[scope]);
  useEffect(()=>{
    const hide=()=>{visible.current=false;clear();};
    const focus=()=>{visible.current=document.visibilityState!=='hidden';};
    const visibility=()=>{if(document.visibilityState==='hidden')hide();else focus();};
    window.addEventListener('blur',hide);window.addEventListener('focus',focus);window.addEventListener('offline',hide);
    document.addEventListener('visibilitychange',visibility);
    return()=>{window.removeEventListener('blur',hide);window.removeEventListener('focus',focus);window.removeEventListener('offline',hide);document.removeEventListener('visibilitychange',visibility);};
  },[]);
  async function open(){
    if(locked||busy||!visible.current)return;
    const controller=new AbortController();clear();active.current=controller;setBusy(true);setOwner(scope);
    const stillCurrent=()=>!controller.signal.aborted&&active.current===controller&&current.current===scope&&visible.current;
    try{
      const team=await workspaceApi.team(identity,controller.signal);if(!stillCurrent())return;
      const bot=team.configuration.bots.find(b=>b.role==='visit_prep'&&b.enabled&&!b.retired&&b.include_evidence);
      const available=team.members.find(b=>b.role==='visit_prep')?.capabilities.some(c=>c.key==='core.visit_prep.read'&&c.state==='enabled');
      if(!bot||!available||team.revision<1)throw new WorkspaceApiError(403);
      const connection=await coreConnectionApi.read(identity,{action:'connection',request_nonce:crypto.randomUUID()},controller.signal);
      if(!stillCurrent())return;
      if(connection.connection_status!=='connected')throw new WorkspaceApiError(403);
      const receipt=await readVisitPrep(identity,{preparation_ref:reference.trim(),workspace_id:crypto.randomUUID(),request_nonce:crypto.randomUUID(),
        connection_sha256:connection.discovery.connection.connection_sha256,bot:{address:'visit_prep',team_revision:team.revision}},controller.signal);
      if(stillCurrent()){setValue(receipt);setBusy(false);}
    }catch(cause){if(!stillCurrent())return;setBusy(false);setError('Patient preparation could not be confirmed. Check your Core selection and current connection.');
      if(cause instanceof WorkspaceApiError&&[401,403,404].includes(cause.status))onAccessLost?.(cause);}
  }
  const receipt=owner===scope&&!locked?value:null,sources=receipt?.package.sources,brief=receipt?.package.brief;
  function source(ref:string){const topic=sources?.topics.find(t=>[t.original_response_id,t.additional_answer_source_id,t.current_revision_id,t.explanation_source_id].includes(ref));
    const node=document.getElementById(sourcePrefix+'-'+topic?.question_key);node?.scrollIntoView?.({block:'nearest'});node?.focus();}
  const items=(title:string,entries:BriefItem[])=>entries.length>0&&<section><h4>{title}</h4><ul>{entries.map((item,i)=><li key={i}>
    {item.text} {item.evidence.map((e,j)=><button type="button" key={j} onClick={()=>source(e.source_ref)} aria-label="Show patient source">[{j+1}]</button>)}
    <details><summary>Patient evidence</summary>{item.evidence.map((e,j)=><p key={j} className="team-prep-content">{e.quote}</p>)}</details>
  </li>)}</ul></section>;
  const words=(t:Topic,original=false)=>{const kind=original?t.initial_response_kind:t.response_kind,answer=original?t.initial_answer:t.answer;
    return kind==='skipped'?'Skipped by recipient':kind===null?'Not answered':t.kind==='choice'?t.choices.find(c=>c.value===answer)?.label??answer:answer;};
  return <section className="team-prep" aria-label="Patient Visit Prep package" aria-busy={busy}>
    <h3><BotAvatar role="visit_prep"/> Patient Visit Prep</h3>
    <p>The patient’s story and priorities, ready to improve the first five minutes. No chart link is required.</p>
    <label>Preparation selected in Cosmaneura
      <input value={reference} maxLength={80} disabled={locked||busy} onChange={event=>{clear();setReference(event.target.value);}}
        placeholder="Paste the preparation reference from Core" autoComplete="off" spellCheck={false}/></label>
    <p className="team-fine">This first connection opens a preparation you selected in Core. A CosmaBot preparation picker is still to come.</p>
    <button className="team-primary" disabled={locked||busy||!/^visit_prep_[0-7][0-9a-hjkmnp-tv-z]{25}$/.test(reference.trim())} onClick={()=>void open()}>
      {busy?'Opening patient preparation…':receipt?'Reload patient preparation':'Open patient preparation'}</button>
    {error&&<p role="alert">{error}</p>}
    {receipt&&sources&&<>
      <p>{sources.preparation.physician_display_name} · {new Date(sources.preparation.scheduled_at).toLocaleString()} · {sources.preparation.timezone_name}</p>
      <p>{sources.actor_role==='caregiver'?'Caregiver report':'Patient report'} · {sources.current_answers_reviewed?'Recipient confirmed this version':'Recipient has not confirmed this version'}.</p>
      <p className="team-fine">Patient-reported information, not verified chart facts. This content is not saved in CosmaBot chat. Reload to check for changes.</p>
      {sources.preparation.patient_id===null&&<p>No patient chart is linked to this preparation.</p>}
      {!sources.current_answers_complete&&<p role="status">Some topics remain unanswered.</p>}
      {receipt.package.status!=='ready'&&<p role="status">{receipt.package.status==='stale'?'The previous AI brief is out of date and is not shown.':'No current AI brief is available.'} The current patient answers are below.</p>}
      {brief&&<><h4>AI-prepared interpretation · version {receipt.package.version}</h4>
        {items('First five minutes',brief.headline?[brief.headline]:[])}{items('Summary',brief.summary)}{items('Visit priorities',brief.visit_priorities)}
        {items('Medications and adherence',brief.medication_and_adherence)}{items('Barriers',brief.barriers)}{items('Uncertainties',brief.uncertainties)}</>}
      <h4>Patient’s own responses</h4>
      {sources.topics.map(t=><section key={t.question_key} id={sourcePrefix+'-'+t.question_key} tabIndex={-1}>
        <h4>{t.prompt}</h4><p className="team-prep-content">{words(t)}</p>
        {t.explanation_words&&<><h5>Recipient explanation</h5><p className="team-prep-content">{t.explanation_words}</p></>}
        {t.changed&&<details><summary>Original response before correction</summary><p className="team-prep-content">{words(t,true)}</p></details>}
        <small>{t.recorded_at?new Date(t.recorded_at).toLocaleString():'Not recorded'}</small>
      </section>)}
      <details><summary>Package version</summary><p className="team-prep-content">{sources.source_version}</p><p>Checked {new Date(receipt.checked_at).toLocaleString()}.</p></details>
    </>}
  </section>;
}

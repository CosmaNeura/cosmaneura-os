import {useEffect,useRef,useState} from 'react';
import {botAddress,type ConversationInput,type ProviderTeam,type Workspace} from './workspace-api';
import {INBOX_DRAFT_QUESTION,type InboxDraftSelection} from './inbox-analysis-contract';

export function InboxAnalysisPanel({selection,workspace,team,selected,locked,onSelect,onSubmit,onClose,onSetup}:{
  selection:InboxDraftSelection;workspace:Workspace;team:ProviderTeam;selected:string;locked:boolean;
  onSelect:(address:string)=>void;onSubmit:(body:ConversationInput)=>Promise<void>;onClose:()=>void;onSetup:()=>void;
}) {
  const [consent,setConsent]=useState(false),[submitting,setSubmitting]=useState(false),[error,setError]=useState(''),inFlight=useRef(false);
  const bots=team.configuration.bots.filter(b=>b.role==='custom'&&b.skills?.includes('inbox_review')&&b.enabled&&!b.retired&&!b.blocked_capabilities?.includes('model_answer'));
  const ready=workspace.id===selection.workspace_id&&workspace.revision===selection.expected_revision&&bots.some(b=>botAddress(b)===selected)&&team.llm.enabled;
  useEffect(()=>{setConsent(false);},[selection,workspace.revision,team.revision,team.llm.model,team.llm.enabled,selected,locked]);
  const submit=async()=>{if(locked||inFlight.current||!consent||!ready)return;inFlight.current=true;setSubmitting(true);setConsent(false);setError('');
    try{await onSubmit({expected_revision:workspace.revision,team_revision:team.revision,idempotency_key:crypto.randomUUID(),role:selected,
      content:INBOX_DRAFT_QUESTION,inbox_analysis:{...selection.analysis,consented:true}});}catch{setError('The draft request could not be confirmed. Check its saved result before starting another request.');}finally{inFlight.current=false;setSubmitting(false);}
  };
  return <section className="team-rehearsal" aria-label="Reviewed Inbox draft">
    {error&&<p role="alert">{error}</p>}<h3>Draft an administrative reply</h3><p>{selection.label}</p>
    <details><summary>Review the selected message and human triage</summary><p style={{whiteSpace:'pre-wrap'}}>{selection.message}</p><strong>Human triage</strong><p style={{whiteSpace:'pre-wrap'}}>{selection.instructions}</p></details>
    {bots.length>0?<label>Drafting coworker<select value={bots.some(b=>botAddress(b)===selected)?selected:''} disabled={locked||submitting} onChange={e=>{setConsent(false);onSelect(e.target.value);}}>
      <option value="" disabled>Select an Inbox coworker</option>{bots.map(b=><option key={botAddress(b)} value={botAddress(b)}>{b.name}</option>)}</select></label>:
      <p>Add or upgrade the Front Desk team and enable its Inbox draft skill. <button disabled={locked} onClick={onSetup}>Open team settings</button></p>}
    {workspace.revision!==selection.expected_revision&&<p role="status">The encounter changed. Review this message against the current encounter in Incoming messages before starting a new draft.</p>}
    {!team.llm.enabled&&<p role="status">AI drafting is not connected.</p>}
    <p>AI receives this message, the human triage instructions and the drafting request. Review the private result before using it. Clinical and urgent decisions require a person.</p>
    <label><input type="checkbox" checked={consent} disabled={locked||submitting||!ready} onChange={e=>setConsent(e.target.checked)}/>Use these selected sources for one AI draft</label>
    <button disabled={locked||submitting||!ready||!consent} onClick={()=>void submit()}>{submitting?'Preparing draft…':'Create private draft'}</button>
    <button disabled={locked||submitting} onClick={onClose}>Close draft selection</button>
  </section>;
}

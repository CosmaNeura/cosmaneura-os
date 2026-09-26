import {useEffect,useRef,useState} from 'react';
import {modelActivityApi} from './model-activity-api';
import type {ActivityRow,ActivityView,AiActivityContext,AiActivitySelection,ModelActivityPage} from './model-activity-contract';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import './AiActivityPanel.css';

export type AiActivityPanelProps={identity:WorkspaceIdentity;context:AiActivityContext;locked:boolean;active?:boolean;
  onOpenEncounter:(selection:AiActivitySelection)=>void|Promise<void>;onAccessLost:(cause:WorkspaceApiError)=>void;onBusyChange?:(busy:boolean)=>void};
const stateLabel:Record<ActivityRow['admission']['state'],string>={reserved:'Waiting to start',running:'In progress',unknown:'Outcome unconfirmed',completed:'Output saved',failed:'AI work failed',abandoned:'Not started — reservation expired'};
const stamp=(value:string)=>new Date(value).toLocaleString();
const selection=(row:ActivityRow):AiActivitySelection=>({workspace_id:row.encounter.workspace_id,appointment_id:row.encounter.appointment_id,entry_id:row.encounter.entry_id});
/** A navigation view only. Existing encounter controllers retain every command and approval. */
export function AiActivityPanel({identity,context,locked,active=true,onOpenEncounter,onAccessLost,onBusyChange}:AiActivityPanelProps){
  const [view,setView]=useState<ActivityView>('attention'),[page,setPage]=useState<ModelActivityPage|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const acceptedIdentity=useRef<WorkspaceIdentity|null>(null);
  const generation=useRef(0),controller=useRef<AbortController|null>(null),busyRef=useRef(false),notify=useRef(onBusyChange),live=useRef({identity,context,active,locked,onOpenEncounter,onAccessLost});
  live.current={identity,context,active,locked,onOpenEncounter,onAccessLost};notify.current=onBusyChange;
  useEffect(()=>{onBusyChange?.(busyRef.current);},[onBusyChange]);
  const same=(current:number,account:WorkspaceIdentity,scope:AiActivityContext)=>current===generation.current&&live.current.active&&live.current.identity===account&&
    live.current.context.box_id===scope.box_id&&live.current.context.owner_id===scope.owner_id&&live.current.context.recovery_scope===scope.recovery_scope;
  function working(value:boolean){busyRef.current=value;setBusy(value);notify.current?.(value);}
  function fail(cause:unknown){setPage(null);
    if(cause instanceof WorkspaceApiError&&[401,403,404].includes(cause.status)){setError('AI activity is unavailable for the current account or source.');live.current.onAccessLost(cause);}
    else setError('AI activity could not be checked. Refresh to read current activity.');
  }
  async function read(next:ActivityView,cursor:string|null=null){
    if(!live.current.active||busyRef.current||live.current.locked)return;
    const current=++generation.current,account=identity,scope={...context};controller.current?.abort();const request=new AbortController();controller.current=request;
    working(true);setError('');setPage(null);setView(next);
    try{const value=await modelActivityApi.read(account,scope,next,cursor,request.signal);if(same(current,account,scope)){acceptedIdentity.current=account;setPage(value);}}
    catch(cause){if(same(current,account,scope))fail(cause);}
    finally{if(same(current,account,scope))working(false);}
  }
  useEffect(()=>{
    generation.current++;controller.current?.abort();busyRef.current=false;setBusy(false);notify.current?.(false);setPage(null);setError('');setView('attention');
    if(active&&!locked)void read('attention');
    return()=>{generation.current++;controller.current?.abort();if(busyRef.current)notify.current?.(false);busyRef.current=false;};
  },[identity,context.box_id,context.owner_id,context.recovery_scope,active]);
  async function open(row:ActivityRow){
    if(!page||busyRef.current||live.current.locked||!live.current.active)return;
    const current=++generation.current,account=identity,scope={...context},snapshot=page;controller.current?.abort();const request=new AbortController();controller.current=request;
    working(true);setError('');setPage(null);
    try{
      const fresh=await modelActivityApi.read(account,scope,snapshot.view,snapshot.page.cursor,request.signal);
      if(!same(current,account,scope))return;
      acceptedIdentity.current=account;
      const found=fresh.rows.find(item=>item.admission.id===row.admission.id);
      if(!found||JSON.stringify(selection(found))!==JSON.stringify(selection(row))){setPage(fresh);setError('This activity changed. Review the refreshed page before opening an encounter.');return;}
      setPage(fresh);
      if(live.current.locked){setError('Finish the current pending change before opening an encounter.');return;}
      await live.current.onOpenEncounter(selection(found));
    }catch(cause){if(same(current,account,scope))fail(cause);}
    finally{if(same(current,account,scope))working(false);}
  }
  // Rendering cannot expose the previous account while passive effects clear state.
  const shown=page&&acceptedIdentity.current===identity&&page.box_id===context.box_id&&page.owner_id===context.owner_id&&page.recovery_scope===context.recovery_scope?page:null;
  if(!active)return null;
  return <section className="ai-activity" aria-label="AI activity">
    <p className="ai-activity-intro">AI answers and private bot drafts.</p>
    <div className="ai-activity-views" role="group" aria-label="Activity view">
      <button aria-pressed={view==='attention'} disabled={busy||locked} onClick={()=>void read('attention')}>Active and unconfirmed</button>
      <button aria-pressed={view==='recent'} disabled={busy||locked} onClick={()=>void read('recent')}>Ended activity</button></div>
    <div className="ai-activity-toolbar">
      {shown&&<p className="ai-activity-note"><time dateTime={shown.as_of}>Observed {stamp(shown.as_of)} (device time)</time></p>}
      <button className="ai-activity-refresh" disabled={busy||locked} onClick={()=>void read(view)}>Refresh activity</button>
    </div>
    {busy&&<p role="status">Checking current AI activity…</p>}{error&&<p role="alert">{error}</p>}
    {locked&&<p>Finish the current pending change before using activity navigation.</p>}
    {shown&&<>
      {shown.coverage.withheld_total>0&&<p className="ai-activity-note">Some activity is withheld because its sources are unavailable.</p>}
      {!shown.rows.length&&<p>No {view==='attention'?'active or unconfirmed':'ended'} activity is available on this page.</p>}
      <ol className="ai-activity-list">{shown.rows.map(row=><li key={row.admission.id}>
        <h3>{row.bot.name}</h3><p>{stateLabel[row.admission.state]} · {row.kind==='conversation'?'AI answer':'Private bot draft'}</p>
        <p>{row.encounter.label}<br/>{row.encounter.starts_at?stamp(row.encounter.starts_at)+' (device time)':row.encounter.source_local_start?.replace('T',' ')+' · Time zone not supplied by the practice'}</p>
        <p className="ai-activity-note">Requested {stamp(row.admission.admitted_at)} · Coworker details at the time of this request.</p>
        <p>{row.admission.usage==='verified'?`Verified tokens: ${row.admission.input_tokens} input · ${row.admission.output_tokens} output`:'Token usage unknown.'}</p>
        <button disabled={busy||locked} onClick={()=>void open(row)}>Open encounter</button>
      </li>)}</ol>
      {shown.page.has_more&&<button disabled={busy||locked} onClick={()=>void read(view,shown.page.next_cursor)}>More activity</button>}
      {shown.page.cursor&&<p className="ai-activity-note">This is a later page. Refresh returns to the first page.</p>}
      <div className="ai-activity-disclosures">
        <details><summary>About this activity</summary>
          <p>Activity and usage are observations; an AI output does not verify that practice work is complete.</p>
          <p>Each page checks current access; outcomes can change. Refresh includes newer activity.</p>
          <p>Activity lists recorded AI work only. Older retained usage can affect allowance without appearing here.</p>
        </details>
        <details><summary>Rolling allowance and verified usage</summary>
          <p>Window: {stamp(shown.usage.window_start)} to {stamp(shown.usage.as_of)}.</p>
          <dl><div><dt>Occupied attempts</dt><dd>{shown.usage.occupied_units}</dd></div><div><dt>Remaining allowance</dt><dd>{shown.usage.remaining_units===null?'No team-wide limit':shown.usage.remaining_units}</dd></div>
            <div><dt>Pending</dt><dd>{shown.usage.pending_units}</dd></div><div><dt>Unconfirmed outcomes</dt><dd>{shown.usage.unknown_units}</dd></div>
            <div><dt>Verified input tokens</dt><dd>{shown.usage.verified_input_tokens??'Unknown'}</dd></div><div><dt>Verified output tokens</dt><dd>{shown.usage.verified_output_tokens??'Unknown'}</dd></div></dl>
          <p>{shown.usage.usage_complete?'All usage in this allowance observation is verified.':'Usage is incomplete. Verified totals cover only observed usage; missing usage is unknown.'} Attempt allowance and token counts are not currency costs or a spending budget.</p>
        </details>
      </div>
    </>}
  </section>;
}

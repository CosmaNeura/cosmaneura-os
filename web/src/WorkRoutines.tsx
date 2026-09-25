import {IncomingBriefNavigation} from './incoming-brief-navigation';
import {RoutineIncomingBrief} from './RoutineIncomingBrief';
import { useContext,useEffect, useId, useRef, useState } from "react";
import { botAddress, supportsSkill, WorkspaceApiError, type AuthenticatedWorkspaceIdentity, type ProviderTeam } from "./workspace-api";
import { routineApi, validSchedule, validRoutineSave, type BriefItem, type BriefSchedule, type Routine, type RoutineSave, type WorkBrief } from "./routine-api";
import { useUnsavedWork } from "./unsaved-work";
import {accountEditorDraft,AccountEditorRecoveryNotice,useAccountEditorRecovery} from "./account-editor-recovery";
import type {AccountEditorDraft} from "./draft-journal";
import {editorData} from "./editor-recovery";
import {DraftStoreError} from "./draft-store";
import {RoutineTimeInput} from "./RoutineTimeInput";
import "./WorkRoutines.css";

const defaults = (): BriefSchedule => ({kind:"practice_work_brief",enabled:false,
  timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,at:"08:00",weekdays:[1,2,3,4,5],
  quiet_start:"18:00",quiet_end:"07:00",max_runs_per_seven_days:5});
const statuses: Record<string,string> = {not_configured:"Not scheduled",paused:"Paused",team_changed:"Review after team changes",
  bot_unavailable:"Bot unavailable",skill_unavailable:"Work status skill unavailable",restricted:"Blocked by your team settings",waiting:"Waiting for scheduled time",
  missed:"Today's time was missed",quiet_hours:"Quiet hours",already_run:"Today's brief is saved",run_limit:"Run limit reached",due:"Brief is due"};
function observedStatus(item:BriefItem):string{
  if(item.state==="superseded")return "Superseded revision · historical, not complete";
  if(item.state==="withdrawn")return "Withdrawn · not complete";
  if(item.human_completion)return "Result checked";
  if(item.state==="closed")return "Closed · completion not verified";
  if(item.work_kind==="visit_preparation")return item.ready_for_review?"Preparation ready for provider review":"Preparation awaiting a result";
  if(item.work_kind==="vendor_delivery")return item.ready_for_review?"Delivery result awaiting review":"Delivery work awaiting a result";
  return item.state==="approved"?"Approved work awaiting a result":"Awaiting result";
}
export function WorkRoutines({identity,team,onAccessLost,onRefreshTeam,onOpenIncoming}: {
  identity:AuthenticatedWorkspaceIdentity;team:ProviderTeam;onAccessLost:(cause:WorkspaceApiError)=>void;onRefreshTeam?:()=>Promise<void>;onOpenIncoming?:(ticketId:string)=>void;
}) {
  const incomingNavigation=useContext(IncomingBriefNavigation);
  const bots=team.configuration.bots.filter(bot=>supportsSkill(bot,"work_status"));
  const [selected,setSelected]=useState("chief");
  const [routine,setRoutine]=useState<Routine|null>(null), [draft,setDraft]=useState(defaults);
  const [report,setReport]=useState<WorkBrief|null>(null), [pending,setPending]=useState<RoutineSave|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState("");
  const [dirty,setDirty]=useState(false),[conflict,setConflict]=useState(false);
  const [base,setBase]=useState({revision:0,teamRevision:0});
  const [checkedRejected,setCheckedRejected]=useState(false);
  const [editing,setEditing]=useState(false);
  const editorId=useId(),editorHeading=useRef<HTMLHeadingElement>(null),overviewHeading=useRef<HTMLHeadingElement>(null),wasEditing=useRef(false);
  useEffect(()=>{
    if(editing)editorHeading.current?.focus();
    else if(wasEditing.current)overviewHeading.current?.focus();
    wasEditing.current=editing;
  },[editing]);
  const restoredSelection=useRef<string|null>(null);
  useUnsavedWork(pending !== null || dirty && JSON.stringify(draft) !== JSON.stringify(routine?.configuration ?? defaults()));
  const generation=useRef(0), controller=useRef(new AbortController());
  const bot=bots.find(bot=>botAddress(bot)===selected);
  const form=(request:RoutineSave|null=pending,configuration=draft,source=base)=>accountEditorDraft("work-routine",{
    selected,configuration,baseRevision:source.revision,teamRevision:source.teamRevision,pending:request},request?.idempotency_key??null);
  const recovery=useAccountEditorRecovery(true,"work-routine",pending||dirty?form():null,busy,failure,identity);
  const stale=dirty&&!!routine&&(base.revision!==routine.revision||base.teamRevision!==routine.team_revision);
  function failure(cause:unknown) {
    if (cause instanceof WorkspaceApiError && [401,403,404].includes(cause.status)) {
      recovery.suspend();
      setReport(null);setRoutine(null);setPending(null);setDraft(defaults());setDirty(false);setEditing(false);
      setError("Private briefs are unavailable for this account or connection.");
      if (cause.status!==404) onAccessLost(cause);
    } else if(cause instanceof WorkspaceApiError && [400,409,422].includes(cause.status)) {
      setConflict(true);setCheckedRejected(false);setError("The schedule was not accepted. Check the current saved schedule before setting this request aside.");
    } else setError("The result could not be confirmed. Retry the same save if one is pending, or refresh.");
  }
  async function load() {
    const current=generation.current;setBusy(true);setError("");setMessage("");
    try {
      await onRefreshTeam?.();
      if(current!==generation.current)return;
      const saved=await routineApi.read(identity,selected,controller.current.signal);
      if(current!==generation.current)return;
      setRoutine(saved);setDraft(saved.configuration??defaults());setDirty(false);setConflict(false);
      setBase({revision:saved.revision,teamRevision:saved.team_revision});
      // A fresh read rechecks access to every source in the historical brief.
      setReport(null);
      if(saved.runs.length) {
        const value=await routineApi.run(identity,selected,saved.runs[0].id,controller.current.signal);
        if(current===generation.current)setReport(value);
      }
    } catch(cause) {if(current===generation.current)failure(cause);}
    finally {if(current===generation.current)setBusy(false);}
  }
  useEffect(()=>{
    generation.current++;controller.current=new AbortController();
    if(restoredSelection.current===selected){restoredSelection.current=null;return()=>{generation.current++;controller.current.abort();};}
    setRoutine(null);setReport(null);setPending(null);setDraft(defaults());setDirty(false);setConflict(false);setEditing(false);
    void load();return()=>{generation.current++;controller.current.abort();};
  },[identity,selected]);
  async function restore(value:AccountEditorDraft,isCurrent:()=>boolean) {
    const data=value.data;editorData(data,"selected,configuration,baseRevision,teamRevision,pending");
    const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
    if(typeof data.selected!=="string"||!(["chief","scribe","visit_prep","follow_up"].includes(data.selected)||uuid.test(data.selected))||
        !Number.isSafeInteger(data.baseRevision)||Number(data.baseRevision)<0||Number(data.baseRevision)>100||
        !Number.isSafeInteger(data.teamRevision)||Number(data.teamRevision)<1)throw new DraftStoreError("integrity");
    const configuration=data.configuration;editorData(configuration,"kind,enabled,timezone,at,weekdays,quiet_start,quiet_end,max_runs_per_seven_days");
    if(configuration.kind!=="practice_work_brief"||typeof configuration.enabled!=="boolean"||typeof configuration.timezone!=="string"||configuration.timezone.length>80||
        typeof configuration.at!=="string"||configuration.at.length>5||!Array.isArray(configuration.weekdays)||configuration.weekdays.length>7||
        !configuration.weekdays.every(day=>Number.isInteger(day)&&day>=1&&day<=7)||new Set(configuration.weekdays).size!==configuration.weekdays.length||
        ![configuration.quiet_start,configuration.quiet_end].every(time=>time===null||typeof time==="string"&&time.length<=5)||
        !Number.isFinite(configuration.max_runs_per_seven_days)||
        data.pending!==null&&!validRoutineSave(data.pending)||value.pending!==((data.pending as RoutineSave|null)?.idempotency_key??null))throw new DraftStoreError("integrity");
    const current=generation.current;
    const latest=await routineApi.read(identity,data.selected,controller.current.signal);
    if(!isCurrent()||current!==generation.current)return;
    if(selected!==data.selected){restoredSelection.current=data.selected;setSelected(data.selected);}
    setRoutine(latest);setReport(null);setDraft(configuration as BriefSchedule);
    setBase({revision:Number(data.baseRevision),teamRevision:Number(data.teamRevision)});
    setPending(data.pending as RoutineSave|null);setDirty(true);setConflict(false);setCheckedRejected(false);setEditing(true);
  }
  async function save(body:RoutineSave) {
    if(busy||recovery.blocked||conflict)return;
    const current=generation.current;setBusy(true);setError("");setMessage("");setPending(body);
    let transmitted=false;
    try {
      await recovery.commit(form(body));
      if(current!==generation.current)return;
      transmitted=true;
      const saved=await routineApi.save(identity,selected,body,controller.current.signal);
      if(current!==generation.current)return;
      const keep=dirty&&JSON.stringify(draft)!==JSON.stringify(body.configuration);
      const savedBase={revision:saved.revision,teamRevision:saved.team_revision};
      await recovery.commit(keep?form(null,draft,savedBase):null);
      if(current!==generation.current)return;
      setRoutine(saved);setBase(savedBase);setPending(null);setDirty(keep);setConflict(false);
      if(!keep)setDraft(saved.configuration??defaults());
      if(current===generation.current)setMessage(body.configuration.enabled?"Schedule saved. Your bot will prepare a private brief when due.":"Routine paused. Saved briefs remain available.");
    } catch(cause) {if(current===generation.current){
      if(!transmitted||cause instanceof DraftStoreError){recovery.suspend();setError(transmitted?"The result could not be saved on this device. Recheck recovery before retrying.":"The schedule was not sent. Recheck device recovery before trying again.");}
      else failure(cause);
    }}
    finally {if(current===generation.current)setBusy(false);}
  }
  async function inspectRejected() {
    if(!pending||!conflict||!recovery.access||busy)return;
    const current=generation.current;setBusy(true);
    try{await recovery.access.authorize();const saved=await routineApi.read(identity,selected,controller.current.signal);
      if(current!==generation.current)return;setRoutine(saved);setCheckedRejected(true);}
    catch(cause){if(current===generation.current)failure(cause);}finally{if(current===generation.current)setBusy(false);}
  }
  async function setAsideRejected() {
    if(!pending||!conflict||!checkedRejected||busy)return;
    const current=generation.current;setBusy(true);
    try{await recovery.commit(form(null));if(current!==generation.current)return;setPending(null);setConflict(false);setCheckedRejected(false);setDirty(true);setError("");}
    catch{recovery.suspend();}finally{if(current===generation.current)setBusy(false);}
  }
  async function openRun(id:string) {
    const current=generation.current;setBusy(true);setReport(null);setError("");
    try {const value=await routineApi.run(identity,selected,id,controller.current.signal);if(current===generation.current)setReport(value);}
    catch(cause){if(current===generation.current)failure(cause);}
    finally{if(current===generation.current)setBusy(false);}
  }
  const locked=busy||pending!==null||conflict||routine===null||recovery.blocked||stale;
  const returnBlocked=busy||pending!==null||conflict||recovery.blocked||recovery.phase==="saving";
  function returnToBriefs(){
    if(returnBlocked)return;
    setEditing(false);
    // Showing a retained observation is a fresh source-authority read, never a run.
    const runId=report?.id??routine?.runs[0]?.id;
    if(runId)void openRun(runId);
  }
  const restricted=bot?.blocked_capabilities?.includes("practice_work_brief") || routine?.status === "restricted";
  const canEnable=!!bot?.enabled&&!bot.retired&&!restricted;
  function change(value:Partial<BriefSchedule>){setDraft({...draft,...value});setDirty(true);setMessage("");}
  return <section className="work-routines" aria-label="Private work briefs">
    <header><div><p className="team-kicker">YOUR BOT'S ROUTINE</p><h2 ref={overviewHeading} tabIndex={-1}>Private work briefs</h2></div>
      <button disabled={busy||pending!==null||recovery.blocked} onClick={()=>void load()}>{dirty||conflict?"Reload saved schedule":"Refresh briefs"}</button></header>
    <p>Have a coworker summarize the shared work available to you, including overdue items and responsibility offers. Each brief is a dated observation.</p>
    <AccountEditorRecoveryNotice recovery={recovery} label="Work routine" onRestore={restore}/>
    <label>Coworker<select value={selected} disabled={busy||pending!==null||dirty||recovery.blocked} onChange={event=>setSelected(event.target.value)}>
      {bots.map(bot=><option key={botAddress(bot)} value={botAddress(bot)}>{bot.name}{bot.retired?" · retired":!bot.enabled?" · paused":""}</option>)}</select></label>
    {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
    {pending&&<p className="team-recovery">This schedule save is unconfirmed. Keep this editor open until the retained request is resolved.</p>}
    {pending&&!busy&&!conflict&&<button disabled={recovery.blocked} onClick={()=>void save(pending)}>Retry same schedule save</button>}
    {pending&&conflict&&<div className="team-recovery"><button disabled={busy||recovery.blocked} onClick={()=>void inspectRejected()}>Check current schedule</button>
      {checkedRejected&&<button disabled={busy||recovery.blocked} onClick={()=>void setAsideRejected()}>Set aside rejected schedule request</button>}</div>}
    {stale&&!pending&&<div className="team-recovery"><p>This unfinished schedule belongs to an earlier saved version. Compare the current schedule and team before continuing.</p>
      <button disabled={busy||recovery.blocked||!routine||routine.team_revision!==team.revision} onClick={()=>{setBase({revision:routine!.revision,teamRevision:routine!.team_revision});setConflict(false);}}>Use these settings with the current schedule</button></div>}
    {busy&&<p role="status">Checking private briefs…</p>}
    {restricted&&<p>Scheduled briefs are blocked by your team settings. Saved schedules and earlier briefs remain available; you can pause this schedule.</p>}
    {routine&&<><p className="team-pill">{statuses[routine.status]}</p>
      {routine.next_scheduled_at&&routine.configuration?.enabled&&!["team_changed","restricted"].includes(routine.status)&&<p>Next scheduled: {new Date(routine.next_scheduled_at).toLocaleString()} (your device time)</p>}
      {routine.team_revision!==team.revision&&<p>Refresh the workspace team before enabling or changing this routine.</p>}
      <div className="routine-overview" hidden={editing}>
        <button aria-controls={editorId} aria-expanded={editing} disabled={busy} onClick={()=>{if(!busy)setEditing(true);}}>Edit schedule</button>
        {dirty&&<p className="team-fine">Unfinished schedule retained. Open Edit schedule to continue. Returning did not save these edits.</p>}
      </div>
      {(dirty||editing)&&!validSchedule(draft)&&<p>Choose a valid time zone, at least one day, a time outside quiet hours, and a limit from 1 to 7.</p>}
      <div id={editorId} className="routine-editor" hidden={!editing}>
        <div className="routine-editor-nav"><button disabled={returnBlocked} onClick={returnToBriefs}>Back to briefs</button>
          <p className="team-fine">Returning keeps your draft. Only Save schedule or Pause routine changes the saved routine.</p></div>
        <h3 ref={editorHeading} tabIndex={-1}>Edit schedule</h3>
        {returnBlocked&&<p className="team-fine">Resolve the pending save or device recovery before returning to briefs.</p>}
      <fieldset disabled={locked} className="routine-form"><legend>Schedule for {bot?.name??"this coworker"}</legend>
        <label className="team-check"><input type="checkbox" checked={draft.enabled} disabled={locked||!canEnable&&!(restricted&&bot?.enabled&&!bot.retired&&draft.enabled)} onChange={event=>change({enabled:event.target.checked})}/>Prepare scheduled briefs</label>
        <label>Time zone<input value={draft.timezone} maxLength={80} onChange={event=>change({timezone:event.target.value})}/></label>
        <RoutineTimeInput label="Brief time" value={draft.at} disabled={locked} onChange={at=>change({at})}/>
        <details className="routine-options"><summary>Repeat, quiet hours and limits</summary>
        <fieldset className="routine-days"><legend>Days</legend>{["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].map((day,index)=><label key={day}>
          <input type="checkbox" checked={draft.weekdays.includes(index+1)} onChange={event=>change({weekdays:event.target.checked?[...draft.weekdays,index+1].sort() : draft.weekdays.filter(d=>d!==index+1)})}/>{day}</label>)}</fieldset>
        <label className="team-check"><input type="checkbox" checked={draft.quiet_start!==null} onChange={event=>change({quiet_start:event.target.checked?"18:00":null,quiet_end:event.target.checked?"07:00":null})}/>Use quiet hours</label>
        {draft.quiet_start!==null&&<><RoutineTimeInput label="Quiet hours start" value={draft.quiet_start} disabled={locked} onChange={quiet_start=>change({quiet_start})}/>
          <RoutineTimeInput label="Quiet hours end" value={draft.quiet_end??""} disabled={locked} onChange={quiet_end=>change({quiet_end})}/></>}
        <label>Maximum briefs in seven days<input type="number" min={1} max={7} value={draft.max_runs_per_seven_days} onChange={event=>change({max_runs_per_seven_days:Number(event.target.value)})}/></label>
        </details>
      </fieldset>
      <p className="team-fine">At most one brief per day, at least 20 hours apart. A restart can catch up within six hours on the same day, outside quiet hours. Team changes require review. The local service must be running.</p>
      <div className="row"><button disabled={locked||!validSchedule(draft)||routine.team_revision!==team.revision||(draft.enabled&&!canEnable)} onClick={()=>void save({expected_revision:routine.revision,team_revision:team.revision,idempotency_key:crypto.randomUUID(),configuration:draft})}>Save schedule</button>
        {routine.configuration?.enabled&&<button disabled={locked} onClick={()=>void save({expected_revision:routine.revision,team_revision:routine.team_revision,idempotency_key:crypto.randomUUID(),configuration:{...routine.configuration!,enabled:false}})}>Pause routine</button>}</div>
      </div>
      <div className="routine-overview" hidden={editing}>
      {!!routine.runs.length&&<details className="routine-history"><summary>Earlier briefs</summary><label>Saved brief<select disabled={busy||pending!==null} value={report?.id??""} onChange={event=>{if(event.target.value)void openRun(event.target.value);}}>
        <option value="">Choose a saved brief</option>{routine.runs.map(run=><option key={run.id} value={run.id}>{run.local_date} · {new Date(run.completed_at).toLocaleTimeString()}</option>)}</select></label></details>}
      {!routine.runs.length&&<p>No saved brief yet.</p>}</div></>}
    <div className="routine-overview" hidden={editing}>
    {report&&<article className="routine-report"><h3>Work observed on {report.local_date}</h3>
      <p>Saved {new Date(report.completed_at).toLocaleString()}. Open Practice work above to check current status or record a result.</p>
      <h4>Shared follow-ups, preparation and delivery</h4>
      <dl>{[["Open",report.counts.open],["Overdue",report.counts.overdue],["Awaiting acceptance",report.counts.awaiting_acceptance],["Owner unavailable",report.counts.responsible_unavailable],["Verified complete",report.counts.verified_complete]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      {report.withheld_sources&&<p>Some sources are no longer available to your account and have been withheld.</p>}
      {report.truncated&&<p>This brief covers only the first 200 available work items.</p>}
      {report.matching_items>report.items.length&&<p>Showing the first {report.items.length} of {report.matching_items} available items.</p>}
      <ul>{report.items.map(item=><li key={item.ticket_id}><strong>{item.body}</strong><br/>{item.responsible.name} · Due {item.due_date} · As observed: {observedStatus(item)}{item.pending_offer?" · Responsibility offered":""}</li>)}</ul>
      {!report.items.length&&<p>No shared work in this brief is currently available to your account.</p>}
      <RoutineIncomingBrief section={report.incoming} blocked={busy||dirty||!!pending||conflict||recovery.blocked||!!incomingNavigation?.blocked}
        onOpen={onOpenIncoming||incomingNavigation?ticketId=>{if(busy||dirty||pending||conflict||recovery.blocked||incomingNavigation?.blocked)return;(onOpenIncoming??incomingNavigation!.openTicket)(ticketId);}:undefined}/>
    </article>}</div>
  </section>;
}

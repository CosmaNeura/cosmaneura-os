import {useEffect,useRef,useState} from "react";
import {botAddress,WorkspaceApiError,type ProviderTeam,type TeamConfiguration,type WorkspaceIdentity} from "./workspace-api";
import {teamSetupApi,type TeamSetup} from "./team-setup-api";
import {applyPreset,replacePresetSlot,upgradeInboxPreset,upgradeMembershipPreset,validTeamConfiguration,RESOURCE_PURPOSES,type CapabilityId,type PresetId,type ReadinessState,
  type ModelUsage,type ResourceInventory,type ResourcePurpose,type SetupProjection,type SetupReview,type SlotName,type TeamRehearsal} from "./team-setup-request";
import "./team-setup.css";

export type ReviewedTeamDraft={review:SetupReview;configurationKey:string;revision:number};
export const readinessLabels:Record<ReadinessState,string>={ready_local:"Available locally",available_for_scoped_request:"Scoped request available",
  requires_encounter:"Encounter review required",connection_required:"Prerequisite missing",disabled_by_owner:"Disabled by your settings",
  paused:"Bot paused",retired:"Bot retired",unavailable_in_beta:"Unavailable in this beta",resource_restricted:"Source restricted by your settings",
  resource_unavailable:"Selected source unavailable",work_limit_reached:"New model work paused or allowance used"};
const capabilityLabels:Record<CapabilityId,string>={saved_notebook:"Saved notebook",saved_evidence:"Saved evidence",work_status:"Work status",
  model_answer:"AI answers",private_draft_handoff:"Private bot assignments",practice_work_brief:"Scheduled work briefs",encounter_prep:"Saved intake preparation",
  consented_capture:"Consented recording",clinical_note:"Clinical note",transcript_correction:"Transcript correction",calendar_availability:"Calendar availability",
  staff_handoff:"Human staff handoff",inbox_operations:"Inbox operations",membership_billing:"Membership and billing"};
const resourceLabels:Record<ResourcePurpose,string>={core_preparation:"Saved intake preparation",scheduling_context:"Scheduling context"};
export function SetupReadiness({configuration,setup,label}:{configuration:TeamConfiguration;setup:SetupProjection;label:string}) {
  return <section aria-label={label} className="team-setup-readiness"><h3>{label}</h3>
    <p>Availability depends on the current connections and the access you allow. Each action checks its required sources and permissions again.</p>
    {configuration.bots.map(bot=><details key={botAddress(bot)}><summary>{bot.name || "Unnamed coworker"} · {bot.retired?"Retired":bot.enabled?"Configured":"Paused"}</summary>
      <ul>{setup.capabilities.filter(c=>c.bot===botAddress(bot)).map(c=><li key={c.capability}>
        <div><strong>{capabilityLabels[c.capability]}</strong><span className="team-pill">{readinessLabels[c.state]}</span></div>
        <p>{c.explanation}</p>
        {c.sources.length>0&&<small>{c.sources.map(s=>s.kind==="runtime"?`Runtime ${s.key}: ${s.enabled?"enabled":"disabled"}`:
          s.kind==="account"?`Account mapping ${s.key}: ${s.state}`:s.kind==="routine"?`Routine revision ${s.revision}: ${s.status.replaceAll("_"," ")}`:
          s.kind==="resource"?`${resourceLabels[s.purpose]}: ${s.selection.replaceAll("_"," ")}`:
          s.kind==="model_work"?`Attempt allowance: ${s.state}; ${s.occupied_units} occupied as of ${s.as_of}`:
            `Required scope: ${s.key.replaceAll("_"," ")}`).join(" · ")}</small>}
      </li>)}</ul></details>)}
  </section>;
}
export type TeamSetupView="all"|"groups"|"limits"|"sources"|"review"|"readiness"|"hidden";
export function TeamSetupPanel({identity,team,draft,setDraft,locked,onCurrentTeam,onReviewChange,onAccessLost,view="all",focusedBot,onAdded,refreshToken=0}:{
  view?:TeamSetupView;focusedBot?:string;onAdded?:()=>void;refreshToken?:number;
  identity:WorkspaceIdentity;team:ProviderTeam;draft:TeamConfiguration;setDraft:(value:TeamConfiguration)=>void;locked:boolean;
  onCurrentTeam:(value:ProviderTeam,setup:SetupProjection)=>void;onReviewChange:(value:ReviewedTeamDraft|null)=>void;onAccessLost:(cause:unknown)=>void;
}) {
  const [loaded,setLoaded]=useState<TeamSetup|null>(null),[unavailable,setUnavailable]=useState(false),[error,setError]=useState("");
  const [reading,setReading]=useState(false),[rehearsing,setRehearsing]=useState(false),[preview,setPreview]=useState<PresetId|null>(null);
  const [replacement,setReplacement]=useState<{id:PresetId;slot:SlotName}|null>(null);
  const [result,setResult]=useState<{key:string;revision:number;value:TeamRehearsal}|null>(null),[reviewed,setReviewed]=useState(false);
  const [refresh,setRefresh]=useState(0);
  const [resources,setResources]=useState<ResourceInventory|null>(null),[usage,setUsage]=useState<ModelUsage|null>(null);
  const configurationKey=JSON.stringify(draft),live=useRef({configurationKey,revision:team.revision,locked});live.current={configurationKey,revision:team.revision,locked};
  const callbacks=useRef({onCurrentTeam,onReviewChange,onAccessLost,setDraft});callbacks.current={onCurrentTeam,onReviewChange,onAccessLost,setDraft};
  const rehearsalController=useRef<AbortController|null>(null);
  const automaticAttempt=useRef<string|null>(null);
  const prerequisitesReady=useRef(false);
  const active=result?.key===configurationKey&&result.revision===team.revision?result:null;
  useEffect(()=>{if(result&&!active){setResult(null);setReviewed(false);}},[configurationKey,team.revision,result,active]);
  useEffect(()=>{callbacks.current.onReviewChange(active&&reviewed?{review:active.value.setup_review,configurationKey,revision:team.revision}:null);
    return()=>callbacks.current.onReviewChange(null);
  },[active,reviewed,configurationKey,team.revision]);
  useEffect(()=>{
    const controller=new AbortController();automaticAttempt.current=null;prerequisitesReady.current=false;setReading(true);setError("");setLoaded(null);setResult(null);setReviewed(false);setResources(null);setUsage(null);
    rehearsalController.current?.abort();setRehearsing(false);
    void teamSetupApi.read(identity,controller.signal).then(async value=>{
      if(controller.signal.aborted||value.team.revision<live.current.revision)return;
      callbacks.current.onCurrentTeam(value.team,value.setup);setLoaded(value);setUnavailable(false);
      if(value.catalog.version>=2) {
        const [inventory,counts]=await Promise.allSettled([teamSetupApi.resources(identity,controller.signal),teamSetupApi.usage(identity,controller.signal)]);
        if(controller.signal.aborted||value.team.revision!==live.current.revision)return;
        if(inventory.status==='fulfilled')setResources(inventory.value);
        if(counts.status==='fulfilled'&&counts.value.team_revision===value.team.revision)setUsage(counts.value);
        for(const result of [inventory,counts])if(result.status==='rejected'&&result.reason instanceof WorkspaceApiError&&[401,403,426].includes(result.reason.status))callbacks.current.onAccessLost(result.reason);
        if(inventory.status==='rejected'||counts.status==='rejected')setError("Current source inventory or attempt counts could not be checked. Your saved policies and editable draft are retained.");
      }
    }).catch(cause=>{
      if(controller.signal.aborted)return;
      if(cause instanceof WorkspaceApiError&&cause.status===404){setUnavailable(true);return;}
      if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status)){callbacks.current.onAccessLost(cause);return;}
      setError("Team setup prerequisites could not be checked. Your editable draft is retained.");
    }).finally(()=>{if(!controller.signal.aborted){prerequisitesReady.current=true;setReading(false);}});
    return()=>{controller.abort();rehearsalController.current?.abort();};
  },[identity,team.revision,refresh,refreshToken]);
  function update(next:TeamConfiguration){setResult(null);setReviewed(false);setError("");callbacks.current.onReviewChange(null);callbacks.current.setDraft(next);}
  function add(){if(!loaded||!preview||locked)return;try{update(applyPreset(draft,loaded.catalog,preview));setPreview(null);onAdded?.();}catch{setError("The complete group cannot be added. Check the current team and retained history limits.");}}
  function replace(){if(!loaded||!replacement||locked)return;try{update(replacePresetSlot(draft,team.configuration,loaded.catalog,replacement.id,replacement.slot));setReplacement(null);}catch{setError("Save the coworker's retirement first and check there is room for a replacement. Its history is retained.");}}
  function allowedSource(address:string,purpose:ResourcePurpose,ref:string) {
    update({...draft,bots:draft.bots.map(bot=>botAddress(bot)!==address?bot:{...bot,resources:{version:1,allowed:[...(bot.resources?.allowed??[]).filter(b=>b.purpose!==purpose),...(ref?[{purpose,resource_ref:ref}]:[])]}})});
  }
  function resourceMode(address:string,inherited:boolean){update({...draft,bots:draft.bots.map(bot=>{if(botAddress(bot)!==address)return bot;const next={...bot};
    if(inherited)delete next.resources;else next.resources={version:1,allowed:[]};return next;})});}
  function sourceBindingsCurrent():boolean {
    return !!resources&&draft.bots.every(bot=>(bot.resources?.allowed??[]).every(binding=>resources.resources.some(r=>r.purpose===binding.purpose&&r.resource_ref===binding.resource_ref)||
      team.configuration.bots.find(saved=>botAddress(saved)===botAddress(bot))?.resources?.allowed.some(saved=>saved.purpose===binding.purpose&&saved.resource_ref===binding.resource_ref)));
  }
  async function rehearse(){
    if(!loaded||locked||rehearsing||!validTeamConfiguration(draft))return;
    if(loaded.catalog.version>=2&&!sourceBindingsCurrent()){setError("Refresh source choices before reviewing a new or changed binding. Existing saved unavailable selections may be retained unchanged.");return;}
    const controller=new AbortController();rehearsalController.current?.abort();rehearsalController.current=controller;
    const key=configurationKey,revision=team.revision;setRehearsing(true);setError("");setResult(null);setReviewed(false);callbacks.current.onReviewChange(null);
    try{
      const value=await teamSetupApi.rehearse(identity,{expected_revision:revision,configuration:structuredClone(draft),scenario_id:loaded.catalog.version>=2?"team_policy_setup.v1":"preset_setup.v1"},controller.signal);
      if(controller.signal.aborted||live.current.configurationKey!==key||live.current.revision!==revision)return;
      // A temporary lock discards this result; allow a fresh check after unlocking.
      if(live.current.locked){automaticAttempt.current=null;return;}
      callbacks.current.setDraft(value.configuration);setResult({key:JSON.stringify(value.configuration),revision,value});
    }catch(cause){
      if(controller.signal.aborted)return;
      if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status))callbacks.current.onAccessLost(cause);
      else setError(cause instanceof WorkspaceApiError?cause.message:"Team settings could not be checked. Your draft is retained.");
    }finally{if(rehearsalController.current===controller){rehearsalController.current=null;setRehearsing(false);}}
  }
  useEffect(()=>{
    if(view!=="review"||!prerequisitesReady.current||!loaded||loaded.team.revision!==team.revision||reading||locked||rehearsing||active||!validTeamConfiguration(draft))return;
    const attempt=JSON.stringify([team.revision,configurationKey,refresh,refreshToken]);
    if(automaticAttempt.current===attempt)return;
    automaticAttempt.current=attempt;
    void rehearse();
  },[view,loaded,reading,locked,rehearsing,active,configurationKey,team.revision,refresh,refreshToken]);
  if(unavailable)return null;
  const chosen=loaded?.catalog.presets.find(p=>p.preset_id===preview);
  const installed=!!chosen&&draft.presets?.some(p=>p.preset_id===chosen.preset_id);
  const additions=installed?0:chosen?.slots.filter(s=>s.address===null).length??0;
  const fits=draft.bots.filter(b=>!b.retired).length+additions<=12&&draft.bots.length+additions<=100;
  const all=view==='all';
  return <section hidden={view==='hidden'} className={`team-setup${all?'':' team-setup-focused'}`} aria-label="Team groups and activation review">
    {all&&<div className="team-section-heading"><div><p className="team-kicker">BUILD YOUR PRIVATE TEAM</p><h2>Choose the help your practice needs</h2>
      <p>Start with your Provider team. Add coworkers, review their limits, then save the configuration you want.</p></div>
      <button disabled={locked||reading||rehearsing} onClick={()=>{setReviewed(false);setResult(null);setRefresh(v=>v+1);}}>Refresh setup prerequisites</button></div>}
    {error&&<p role="alert">{error}</p>}{reading&&<p role="status">Checking current team prerequisites…</p>}
    {loaded&&<>
      {(all||view==='groups')&&<><div className="team-preset-options">{loaded.catalog.presets.map(p=><button key={p.preset_id} aria-pressed={preview===p.preset_id}
        disabled={locked||rehearsing} onClick={()=>{setPreview(p.preset_id);setReplacement(null);}}><strong>{p.label}</strong><span>{p.purpose}</span>
        <small>{draft.presets?.some(b=>b.preset_id===p.preset_id)?"Included in this draft":"Preview group"}</small></button>)}</div>
      {chosen&&<div className="team-preset-preview" aria-label={`${chosen.label} preview`}><h3>{chosen.label}</h3>
        <p>{installed?"This group is already in your draft. Names, settings and bot identities are preserved.":`${additions} new coworkers; ${chosen.slots.length-additions} existing coworkers reused. Your Provider team settings stay as you set them.`}</p>
        <ul>{chosen.slots.map(slot=><li key={slot.slot}><strong>{slot.name}</strong> · {slot.address?"Reuse existing coworker":slot.enabled?"New configured coworker":"New paused coworker"}</li>)}</ul>
        {chosen.unavailable_capabilities.length>0&&<p>{chosen.unavailable_capabilities.map(c=>capabilityLabels[c]).join(", ")} remains unavailable in this beta. Turning on chat does not connect this operational lane.</p>}
        <p>{draft.bots.filter(b=>!b.retired).length+additions} of 12 current coworkers · {draft.bots.length+additions} of 100 retained records.</p>
        {!fits&&<p role="status">This complete group will not fit. Retire an added coworker to make room; retained history is never removed.</p>}
        <button disabled={locked||!!installed||!fits||rehearsing} onClick={add}>Add {chosen.label} to draft</button>
        {chosen.preset_id==='front_desk'&&chosen.version===2&&draft.presets?.some(p=>p.preset_id==='front_desk'&&p.version===1)&&<div>
          <p>Upgrade enables reviewed Inbox drafting. Your current coworker identity, settings and restrictions are preserved. Review this change before saving.</p>
          <button disabled={locked||rehearsing} onClick={()=>{try{update(upgradeInboxPreset(draft,loaded.catalog));setError('');}catch{setError('Replace the retired Inbox coworker before upgrading.');}}}>Add Inbox draft skill to team draft</button>
        </div>}
        {chosen.preset_id==='practice_manager'&&chosen.version===2&&draft.presets?.some(p=>p.preset_id==='practice_manager'&&p.version===1)&&<div>
          <p>Enable selected membership and payment evidence review. Your coworker identity, settings and restrictions are preserved. Review this change before saving.</p>
          <button disabled={locked||rehearsing} onClick={()=>{try{update(upgradeMembershipPreset(draft,loaded.catalog));setError('');}catch{setError('Replace the retired Membership/Billing coworker before upgrading.');}}}>Add Membership/Billing review skill to team draft</button>
        </div>}
        {(draft.presets?.find(p=>p.preset_id===chosen.preset_id)&&chosen.slots.filter(slot=>slot.address===null&&
          team.configuration.bots.some(bot=>bot.instance_id===team.configuration.presets?.find(p=>p.preset_id===chosen.preset_id)?.slots[slot.slot]&&bot.retired))||[]).map(slot=>
          <button key={slot.slot} disabled={locked||rehearsing} onClick={()=>setReplacement({id:chosen.preset_id,slot:slot.slot})}>Preview replacement for {slot.name}</button>)}
      </div>}
      {replacement&&<div className="team-preset-preview"><p>A replacement receives a new identity. The saved retired coworker and its history remain retained.</p>
        <button disabled={locked||rehearsing} onClick={replace}>Add replacement to draft</button><button onClick={()=>setReplacement(null)}>Cancel replacement</button></div>}</>}
      {loaded.catalog.version>=2&&(all||view==='limits'||view==='sources')&&<section aria-label="Team model and source policy" className="team-rehearsal"><h3>{all?"Control new model work and source choices":view==='limits'?"AI work limit":"Source access"}</h3>
        {(all||view==='limits')&&<>
        <p>Attempt limits count admitted AI answers and private drafts over a rolling 24 hours. They are not currency budgets, service grants or recording limits. Existing encounter and retry limits still apply.</p>
        {draft.model_work?<><label>Team attempts per 24 hours<input type="number" min={0} max={1000} step={1} value={draft.model_work.max_attempts_per_24h} disabled={locked||rehearsing}
          onChange={e=>{const n=Number(e.target.value);if(e.target.value!==''&&Number.isInteger(n)&&n>=0&&n<=1000)update({...draft,model_work:{version:1,max_attempts_per_24h:n}});}}/></label>
          <p>{draft.model_work.max_attempts_per_24h===0?"Zero pauses new model work. Saved requests can still be checked.":`Draft limit: ${draft.model_work.max_attempts_per_24h} admitted attempts per rolling 24 hours.`}</p>
          <button disabled={locked||rehearsing} onClick={()=>{const next={...draft};delete next.model_work;update(next);}}>Remove team attempt limit from draft</button></>:
          <><p>No team-wide attempt limit is configured.</p><button disabled={locked||rehearsing} onClick={()=>update({...draft,model_work:{version:1,max_attempts_per_24h:0}})}>Add attempt limit to draft</button></>}
        {usage&&<p>Current saved policy: {usage.policy===null?"no team-wide limit":usage.policy.max_attempts_per_24h===0?"new model work paused":`${usage.policy.max_attempts_per_24h} attempts`} · {usage.occupied_units} occupied · {usage.remaining_units===null?"no team-wide remaining count":`${usage.remaining_units} remaining`} as of {usage.as_of}. {usage.unknown_units} outcomes unconfirmed. Counts are informational; each new request rechecks them.</p>}</>}
        {(all||view==='sources')&&<>
        <p>These source choices cover saved intake preparation and scheduling context only. They do not grant connector access, affect capture stop/recovery, or replace authorization for an already-approved appointment action.</p>
        {!resources&&<p role="status">Current source inventory unavailable. Retained source restrictions remain in place.</p>}
        {draft.bots.filter(bot=>all||!focusedBot||botAddress(bot)===focusedBot).map(bot=><details open={!all} key={botAddress(bot)} data-source-editor={botAddress(bot)}><summary>{bot.name||"Unnamed coworker"} · source choices</summary>
          {!bot.resources?<><p>Inherited current source checks apply to both purposes.</p><button disabled={locked||rehearsing||!!bot.retired||!resources} onClick={()=>resourceMode(botAddress(bot),false)}>Restrict {bot.name} sources</button></>:
          <><p>Only selected current mappings are permitted. An empty selection denies that purpose.</p>{RESOURCE_PURPOSES.map(purpose=>{
            const selected=bot.resources!.allowed.find(b=>b.purpose===purpose)?.resource_ref??'',current=resources?.resources.find(r=>r.purpose===purpose);
            const stale=!!selected&&selected!==current?.resource_ref;
            return <label key={purpose}>{resourceLabels[purpose]} for {bot.name}<select value={selected} disabled={locked||rehearsing||!!bot.retired||!resources}
              onChange={e=>allowedSource(botAddress(bot),purpose,e.target.value)}><option value="">Not allowed</option>
              {stale&&<option value={selected}>Selected source unavailable · retained restriction</option>}{current&&<option value={current.resource_ref}>{current.label}</option>}</select>
              {!current&&<small>No current reviewed mapping is available.</small>}{stale&&<small>This saved selection remains unavailable. It is never replaced with inherited access automatically.</small>}</label>;
          })}<button disabled={locked||rehearsing||!!bot.retired} onClick={()=>resourceMode(botAddress(bot),true)}>Use inherited source checks for {bot.name}</button></>}
        </details>)}</> }
        <p>Policy changes are checked before saving. Your review applies only to the current settings.</p>
      </section>}
      {(all||view==='review')&&<div className="team-rehearsal"><h3>Review team access</h3>
        <p>{all?"Check your settings, then review the available capabilities before saving.":"We check these settings automatically. Review the available capabilities before saving."} Each action still checks its current account and encounter access.</p>
        {rehearsing&&<p role="status">Checking team settings…</p>}
        {(all||!!error||!!active)&&<button disabled={locked||reading||rehearsing||!validTeamConfiguration(draft)} onClick={()=>void rehearse()}>{active?"Check settings again":"Check team settings"}</button>}
        {!validTeamConfiguration(draft)&&<p>Finish each coworker's name and required job before checking settings.</p>}
        {active&&<><p role="status">Settings checked. Review the capability summary and confirm these changes.</p>
          <SetupReadiness configuration={active.value.configuration} setup={active.value.setup} label="Capabilities with these settings"/>
          <label className="team-check"><input type="checkbox" checked={reviewed} disabled={locked} onChange={e=>setReviewed(e.target.checked)}/>
            I reviewed these team changes and the available capabilities.</label>
          <p>Save to apply this configuration. Further edits require a fresh check and review.</p></>}
      </div>}
      {(view==='readiness'||!active&&all)&&<SetupReadiness configuration={loaded.team.configuration} setup={loaded.setup} label="Saved team prerequisites"/>}
    </>}
  </section>;
}

import {useCallback,useEffect,useRef,useState} from 'react';
import {ProviderTeamSettings,type ProviderTeamSettingsView} from './ProviderTeamSettings';
import {TeamSetupPanel,type ReviewedTeamDraft,type TeamSetupView} from './TeamSetupPanel';
import {setupChange,validTeamConfiguration,type SetupProjection} from './team-setup-request';
import {botAddress,type BotAddress,type ProviderTeam,type TeamConfiguration,type WorkspaceIdentity} from './workspace-api';
import {AiActivityPanel} from './AiActivityPanel';
import type {AiActivityContext,AiActivitySelection} from './model-activity-contract';
import './team-configuration-flow.css';

export type TeamConfigurationFlowProps={
  identity:WorkspaceIdentity;team:ProviderTeam;draft:TeamConfiguration;setDraft:(draft:TeamConfiguration)=>void;
  selected:BotAddress;setSelected:(address:BotAddress)=>void;locked:boolean;setupAvailable:boolean;reviewRequired:boolean;
  onCurrentTeam:(team:ProviderTeam,setup:SetupProjection)=>void;onReviewChange:(review:ReviewedTeamDraft|null)=>void;
  activity?:{context:AiActivityContext;onOpenEncounter:(selection:AiActivitySelection)=>void|Promise<void>;onBusyChange?:(busy:boolean)=>void};
  onAccessLost:(cause:unknown)=>void;onSave:()=>void;onClose:()=>void;onRefresh:()=>void|Promise<void>;
};
type Page='overview'|'edit'|'advanced'|'sources'|'practice'|'limits'|'preferences'|'add'|'groups'|'review'|'readiness'|'activity';
const titles:Record<Page,string>={overview:'Your private team',edit:'Coworker details',advanced:'Skills and permissions',sources:'Source access',practice:'Practice context',limits:'AI work limit',preferences:'Team preferences',add:'Add a coworker',groups:'Add a team group',review:'Review team changes',readiness:'What your team can do',activity:'AI activity'};

function ChangeSummary({team,draft}:Pick<TeamConfigurationFlowProps,'team'|'draft'>){
  const changed=draft.bots.filter(bot=>JSON.stringify(bot)!==JSON.stringify(team.configuration.bots.find(old=>botAddress(old)===botAddress(bot))));
  return <section className="team-change-summary" aria-label="Exact draft changes">
    {changed.length===0&&draft.practice_context===team.configuration.practice_context&&JSON.stringify(draft.model_work)===JSON.stringify(team.configuration.model_work)&&JSON.stringify(draft.presets)===JSON.stringify(team.configuration.presets)?<p>{team.revision?'No settings have changed.':'Your Provider team is ready to review and save.'}</p>:null}
    {changed.map(bot=>{const old=team.configuration.bots.find(item=>botAddress(item)===botAddress(bot));return <article key={botAddress(bot)}>
      <h3>{bot.name||'Unnamed coworker'} <small>{!old?'New coworker':bot.retired&&!old.retired?'Retiring':'Updated'}</small></h3>
      {(bot.job_focus!==old?.job_focus||!old)&&<p>{bot.job_focus||'No additional job focus'}</p>}
      {(bot.working_preferences!==old?.working_preferences)&&<p className="team-review-text">{bot.working_preferences||'Additional instructions removed'}</p>}
      {(!old||bot.enabled!==old.enabled)&&<p>{bot.retired?'Retired; history retained':bot.enabled?'Enabled for permitted work':'Paused; history retained'}</p>}
      {bot.response_style!==old?.response_style&&<p>Responses: {bot.response_style==='detailed'?'More detail':'Brief'}</p>}
      {bot.include_notebook!==old?.include_notebook&&<p>Saved notebook: {bot.include_notebook?'Allowed within the current encounter':'Not allowed'}</p>}
      {bot.include_evidence!==old?.include_evidence&&<p>Saved evidence: {bot.include_evidence?'Allowed within the current encounter':'Not allowed'}</p>}
      {JSON.stringify(bot.skills)!==JSON.stringify(old?.skills)&&<p>Skills: {(bot.skills??[]).map(key=>team.custom_skills?.find(skill=>skill.key===key)?.label??key.replaceAll('_',' ')).join(', ')||'None'}</p>}
      {JSON.stringify(bot.blocked_capabilities)!==JSON.stringify(old?.blocked_capabilities)&&<p>Blocked work: {(bot.blocked_capabilities??[]).map(key=>({model_answer:'AI answers',private_draft_handoff:'Private bot assignments',practice_work_brief:'Scheduled work briefs'})[key]).join(', ')||'No added capability restrictions'}</p>}
      {JSON.stringify(bot.resources)!==JSON.stringify(old?.resources)&&<p>Sources: {bot.resources?bot.resources.allowed.length?`Restricted to the selected reviewed mappings for ${bot.resources.allowed.map(binding=>binding.purpose==='core_preparation'?'visit preparation':'scheduling').join(' and ')}`:'No preparation or scheduling sources allowed':'Inherited current source checks'}</p>}
    </article>;})}
    {draft.practice_context!==team.configuration.practice_context&&<article><h3>Practice context</h3><p className="team-review-text">{draft.practice_context||'No additional practice context'}</p></article>}
    {JSON.stringify(draft.model_work)!==JSON.stringify(team.configuration.model_work)&&<p>Team AI work limit: {draft.model_work?draft.model_work.max_attempts_per_24h===0?'New model work paused':`${draft.model_work.max_attempts_per_24h} attempts per rolling 24 hours`:'No team-wide attempt limit'}.</p>}
    {JSON.stringify(draft.presets)!==JSON.stringify(team.configuration.presets)&&<p>Team groups: {(draft.presets??[]).map(group=>group.preset_id.replaceAll('_',' ')).join(', ')||'None'}.</p>}
  </section>;
}

/** Parent retains the owner-scoped draft and exact save journal across all pages. */
export function TeamConfigurationFlow(props:TeamConfigurationFlowProps){
  const {identity,team,draft,setDraft,selected,setSelected,locked,setupAvailable,reviewRequired,onCurrentTeam,onReviewChange,onAccessLost,onSave,onClose,onRefresh}=props;
  const [activityBusy,setActivityBusy]=useState(false);
  const activityBusyChange=useCallback((value:boolean)=>{setActivityBusy(value);props.activity?.onBusyChange?.(value);},[props.activity?.onBusyChange]);
  useEffect(()=>{if(!props.activity){setActivityBusy(false);setPage(value=>value==='activity'?'preferences':value);}},[!!props.activity]);
  const [page,setPage]=useState<Page>('overview'),[refreshToken,setRefreshToken]=useState(0),heading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{heading.current?.focus();},[page]);
  const bot=draft.bots.find(item=>botAddress(item)===selected)??draft.bots[0];
  const valid=validTeamConfiguration(draft),changed=JSON.stringify(team.configuration)!==JSON.stringify(draft),needsCheck=setupChange(team.configuration,draft);
  const providerView:ProviderTeamSettingsView=['overview','edit','advanced','practice','add'].includes(page)?page as ProviderTeamSettingsView:'hidden';
  const setupView:TeamSetupView=page==='review'?(needsCheck?'review':'hidden'):['groups','limits','sources','readiness'].includes(page)?page as TeamSetupView:'hidden';
  const back=()=>{if(page==='activity'&&(locked||activityBusy))return;setPage(page==='sources'?'advanced':page==='advanced'?'edit':page==='practice'||page==='limits'||page==='readiness'||page==='activity'?'preferences':'overview');};
  const common={team,draft,setDraft,selected,setSelected,locked:locked||activityBusy,setupAvailable,reviewRequired,onSave,onClose};
  return <section className="team-configuration-flow" aria-label="Team configuration" data-page={page}>
    <header className="team-flow-heading"><div>{page!=='overview'&&<button className="team-flow-back" disabled={page==='activity'&&(locked||activityBusy)} onClick={back}>← Back</button>}<h2 tabIndex={-1} ref={heading}>{titles[page]}</h2>
      {page==='overview'?<p>{team.revision?'Your saved team is ready for each visit. Personalization is optional.':'Your team comes ready to use: Scribe, Visit Prep, Follow-up, Chief and Research. No need to fill out each bot.'}</p>:['edit','advanced','sources'].includes(page)?<p>{bot?.name||'New coworker'}</p>:null}</div>
      </header>
    {page==='overview'&&<p className="team-flow-status">{changed?'Unsaved team changes':team.revision?'Saved team':'Not yet saved'} · {draft.bots.filter(item=>!item.retired).length} coworkers</p>}
    <ProviderTeamSettings {...common} view={providerView} setSelected={address=>{setSelected(address);if(page==='overview')setPage('edit');}} onBotAdded={()=>setPage('edit')}/>
    {page==='overview'&&<nav aria-label="Team configuration choices" className="team-flow-links"><button disabled={locked} onClick={()=>setPage('add')}>Add a coworker <span aria-hidden="true">›</span></button><button disabled={locked} onClick={()=>setPage('groups')}>Add a team group <span aria-hidden="true">›</span></button><button onClick={()=>setPage('preferences')}>Team preferences <span aria-hidden="true">›</span></button></nav>}
    {page==='edit'&&<button className="team-flow-option" onClick={()=>setPage('advanced')}>Skills, permissions and source access →</button>}
    {page==='advanced'&&<button className="team-flow-option" onClick={()=>setPage('sources')}>Choose preparation and scheduling sources →</button>}
    {page==='preferences'&&<nav aria-label="Team preferences" className="team-flow-links"><button onClick={()=>setPage('practice')}>Practice context <span aria-hidden="true">›</span></button><button onClick={()=>setPage('limits')}>AI work limit <span aria-hidden="true">›</span></button>{props.activity&&<button disabled={locked||activityBusy} onClick={()=>{if(!locked&&!activityBusy)setPage('activity');}}>AI activity <span aria-hidden="true">›</span></button>}<button onClick={()=>setPage('readiness')}>What your team can do <span aria-hidden="true">›</span></button><button disabled={locked} onClick={()=>{setRefreshToken(value=>value+1);onReviewChange(null);void onRefresh();}}>Refresh current settings</button></nav>}
    {page==='review'&&<><ChangeSummary team={team} draft={draft}/><p className="team-flow-note">Saving configures your private team. External actions still require separate approval.</p>{!valid&&<p role="alert">Finish each coworker's name and each custom coworker's job before saving.</p>}</>}
    <TeamSetupPanel identity={identity} team={team} draft={draft} setDraft={setDraft} locked={locked}
      onCurrentTeam={onCurrentTeam} onReviewChange={onReviewChange} onAccessLost={onAccessLost}
      view={setupView} refreshToken={refreshToken} focusedBot={bot?botAddress(bot):undefined} onAdded={()=>setPage('overview')}/>
    {props.activity&&<AiActivityPanel identity={identity} context={props.activity.context} active={page==='activity'} locked={locked} onOpenEncounter={props.activity.onOpenEncounter} onAccessLost={onAccessLost} onBusyChange={activityBusyChange}/>}
    {!['add','groups','preferences','readiness','activity'].includes(page)&&<footer className="team-flow-footer">
      {page==='review'?<button className="team-primary" disabled={locked||reviewRequired||!valid||!changed&&team.revision>0} onClick={onSave}>{team.revision?'Save team changes':'Set up my team'}</button>:
      page==='overview'?<button className="team-primary" disabled={locked} onClick={()=>setPage('review')}>{team.revision?'Review changes':'Use this team'}</button>:
      <button className="team-primary" disabled={locked} onClick={()=>setPage(page==='advanced'?'edit':page==='sources'?'advanced':page==='limits'?'preferences':'overview')}>Done editing</button>}
    </footer>}
  </section>;
}

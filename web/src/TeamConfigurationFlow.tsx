import {teamConfigurationDiff,teamConfigurationChanged} from './team-configuration-diff';
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
  selected:BotAddress;setSelected:(address:BotAddress)=>void;locked:boolean;inputLocked?:boolean;resetToken?:number;active?:boolean;setupAvailable:boolean;reviewRequired:boolean;
  onCurrentTeam:(team:ProviderTeam,setup:SetupProjection)=>void;onReviewChange:(review:ReviewedTeamDraft|null)=>void;
  activity?:{context:AiActivityContext;onOpenEncounter:(selection:AiActivitySelection)=>void|Promise<void>;onBusyChange?:(busy:boolean)=>void};
  onAccessLost:(cause:unknown)=>void;onSave:()=>void;onClose:()=>void;onRefresh:()=>void|Promise<void>;
};
type Page='overview'|'edit'|'advanced'|'sources'|'practice'|'limits'|'preferences'|'add'|'groups'|'review'|'readiness'|'activity';
const titles:Record<Page,string>={overview:'Your private team',edit:'Coworker details',advanced:'Skills and permissions',sources:'Source access',practice:'Practice profile',limits:'AI work limit',preferences:'Team preferences',add:'Add a coworker',groups:'Add a team group',review:'Review team changes',readiness:'What your team can do',activity:'AI activity'};

const fieldLabels:Record<string,string>={name:'Name',job_focus:'Job',working_preferences:'Working preferences',enabled:'Enabled',response_style:'Response length',retired:'Remove from active team',include_notebook:'Saved notebook access',include_evidence:'Saved evidence access',skills:'Skills',blocked_capabilities:'Blocked work',resources:'Preparation and scheduling sources',practice_profile:'Practice profile',practice_context:'Additional practice instructions',presets:'Team groups',model_work:'AI work limit'};
function displayValue(value:unknown):string {if(value===true)return 'Yes';if(value===false)return 'No';if(value===null||value===undefined||value==='')return 'None';if(typeof value==='string')return value.replaceAll('_',' ');if(Array.isArray(value))return value.map(displayValue).join(', ')||'None';if(typeof value==='object'&&'practice_name' in value)return Object.entries(value).filter(([key,value])=>key!=='version'&&value).map(([key,value])=>`${key.replaceAll('_',' ')}: ${value}`).join(' · ');if(typeof value==='object'&&'max_attempts_per_24h' in value)return `${value.max_attempts_per_24h} attempts per 24 hours`;if(typeof value==='object'&&'allowed' in value)return ((value.allowed as {purpose:string}[]).map(item=>item.purpose.replaceAll('_',' ')).join(', '))||'No source access';return 'Updated choices';}
function ChangeSummary({team,draft}:Pick<TeamConfigurationFlowProps,'team'|'draft'>){const diff=teamConfigurationDiff(team.configuration,draft);
  return <section className="team-change-summary" aria-label="Exact draft changes">{!diff.count&&<p>{team.revision?'No settings have changed.':'Your Provider team is ready to review and save.'}</p>}
    {diff.bots.map(bot=><article key={bot.address}><h3>{bot.name} <small>{bot.added?'New coworker':'Updated'}</small></h3><dl>{bot.fields.map(change=><div key={change.field}><dt>{fieldLabels[change.field]??change.field}</dt><dd>{bot.added?'':displayValue(change.before)+' → '}{displayValue(change.after)}</dd></div>)}</dl></article>)}
    {diff.settings.map(change=><article key={change.field}><h3>{fieldLabels[change.field]}</h3><p>{displayValue(change.before)} → {displayValue(change.after)}</p></article>)}
  </section>;
}

/** Parent retains the owner-scoped draft and exact save journal across all pages. */
export function TeamConfigurationFlow(props:TeamConfigurationFlowProps){
  const {identity,team,draft,setDraft,selected,setSelected,locked,setupAvailable,reviewRequired,onCurrentTeam,onReviewChange,onAccessLost,onSave,onClose,onRefresh}=props;
  const [activityBusy,setActivityBusy]=useState(false);
  const activityBusyChange=useCallback((value:boolean)=>{setActivityBusy(value);props.activity?.onBusyChange?.(value);},[props.activity?.onBusyChange]);
  useEffect(()=>{if(!props.activity){setActivityBusy(false);setPage(value=>value==='activity'?'preferences':value);}},[!!props.activity]);
  const [page,setPage]=useState<Page>('overview'),[refreshToken,setRefreshToken]=useState(0),heading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{if(props.active!==false)heading.current?.focus();},[page,props.active]);
  useEffect(()=>{if(props.active===false)setPage('overview');},[props.active]);
  const bot=draft.bots.find(item=>botAddress(item)===selected)??draft.bots[0];
  const valid=validTeamConfiguration(draft),changed=teamConfigurationChanged(team.configuration,draft),needsCheck=setupChange(team.configuration,draft);
  const providerView:ProviderTeamSettingsView=['overview','edit','advanced','practice','add'].includes(page)?page as ProviderTeamSettingsView:'hidden';
  const setupView:TeamSetupView=page==='review'?(needsCheck?'review':'hidden'):['groups','limits','sources','readiness'].includes(page)?page as TeamSetupView:'hidden';
  const back=()=>{if(page==='activity'&&(locked||activityBusy))return;setPage(page==='sources'||page==='advanced'||page==='edit'?'overview':page==='practice'||page==='limits'||page==='readiness'||page==='activity'?'preferences':'overview');};
  const common={team,draft,setDraft,selected,setSelected,locked:locked||activityBusy,inputLocked:(props.inputLocked??locked)||activityBusy,setupAvailable,reviewRequired,onSave,onClose};
  return <section className="team-configuration-flow" aria-label="Team configuration" data-page={page}>
    <header className="team-flow-heading"><div>{page!=='overview'&&<button className="team-flow-back" disabled={page==='activity'&&(locked||activityBusy)} onClick={back}>← Back</button>}<h2 tabIndex={-1} ref={heading}>{titles[page]}</h2>
      {page==='overview'?<p>{team.revision?'Your saved team is ready for each visit. Personalization is optional.':'Your team comes ready to use: Scribe, Visit Prep, Follow-up, Chief and Research. No need to fill out each bot.'}</p>:['edit','advanced','sources'].includes(page)?<p>{bot?.name||'New coworker'}</p>:null}</div>
      </header>
    {page==='overview'&&<p className="team-flow-status">{changed?`${teamConfigurationDiff(team.configuration,draft).count} unsaved field ${teamConfigurationDiff(team.configuration,draft).count===1?'change':'changes'}`:team.revision?'Saved team':'Not yet saved'} · {draft.bots.filter(item=>!item.retired).length} coworkers</p>}
    <ProviderTeamSettings {...common} view={providerView} setSelected={address=>{setSelected(address);if(page==='overview')setPage('edit');}} onBotAdded={()=>setPage('edit')}/>
    {page==='overview'&&<nav aria-label="Team configuration choices" className="team-flow-links"><button disabled={locked} onClick={()=>setPage('add')}>Add a coworker <span aria-hidden="true">›</span></button><button disabled={locked} onClick={()=>setPage('groups')}>Add a team group <span aria-hidden="true">›</span></button><button onClick={()=>setPage('preferences')}>Team preferences <span aria-hidden="true">›</span></button></nav>}
    {['edit','advanced','sources'].includes(page)&&<nav className="team-material-tabs" aria-label="Coworker settings"><button aria-pressed={page==='edit'} onClick={()=>setPage('edit')}>About</button><button aria-pressed={page==='advanced'} onClick={()=>setPage('advanced')}>Permissions</button><button aria-pressed={page==='sources'} onClick={()=>setPage('sources')}>Sources</button></nav>}
    {page==='preferences'&&<nav aria-label="Team preferences" className="team-flow-links"><button onClick={()=>setPage('practice')}>Practice profile <span aria-hidden="true">›</span></button><button onClick={()=>setPage('limits')}>AI work limit <span aria-hidden="true">›</span></button>{props.activity&&<button disabled={locked||activityBusy} onClick={()=>{if(!locked&&!activityBusy)setPage('activity');}}>AI activity <span aria-hidden="true">›</span></button>}<button onClick={()=>setPage('readiness')}>What your team can do <span aria-hidden="true">›</span></button><button disabled={locked} onClick={()=>{setRefreshToken(value=>value+1);onReviewChange(null);void onRefresh();}}>Refresh current settings</button></nav>}
    {page==='review'&&<><ChangeSummary team={team} draft={draft}/><p className="team-flow-note">Saving configures your private team. External actions still require separate approval.</p>{!valid&&<p role="alert">Finish each coworker's name and each custom coworker's job before saving.</p>}</>}
    {page==='edit'&&(!bot?.name.trim()||bot?.role==='custom'&&!bot.job_focus?.trim())&&<p role="alert">Enter a coworker name and the required job before accepting this addition.</p>}
    <TeamSetupPanel identity={identity} team={team} draft={draft} setDraft={setDraft} locked={locked}
      onCurrentTeam={onCurrentTeam} onReviewChange={onReviewChange} onAccessLost={onAccessLost}
      view={setupView} refreshToken={refreshToken+(props.resetToken??0)} focusedBot={bot?botAddress(bot):undefined} onAdded={()=>setPage('overview')}/>
    {props.activity&&<AiActivityPanel identity={identity} context={props.activity.context} active={page==='activity'} locked={locked} onOpenEncounter={props.activity.onOpenEncounter} onAccessLost={onAccessLost} onBusyChange={activityBusyChange}/>}
    {!['add','groups','preferences','readiness','activity'].includes(page)&&<footer className="team-flow-footer">
      {page==='review'?<><p className="team-fine" role="status">{!valid?'Complete required fields before saving.':reviewRequired?'Review the capability check above to enable Save.':!changed&&team.revision>0?'No changes to save.':'Ready to save your private team.'}</p><button className="team-primary" disabled={locked||reviewRequired||!valid||!changed&&team.revision>0} onClick={onSave}>{team.revision?'Save team changes':'Set up my team'}</button></>:
      page==='overview'?<button className="team-primary" disabled={locked} onClick={()=>setPage('review')}>{team.revision?'Review changes':'Use this team'}</button>:
      <button className="team-primary" disabled={locked||!bot?.name.trim()||bot?.role==='custom'&&!bot.job_focus?.trim()} onClick={()=>setPage(page==='advanced'?'edit':page==='sources'?'advanced':page==='limits'?'preferences':'overview')}>Done editing</button>}
    </footer>}
  </section>;
}

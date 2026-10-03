import {useEffect, useRef, useState, type ReactNode} from 'react';
import './settings-hub.css';
import {ATHENA_CONNECTION_BUILD} from './AthenaConnectionPanel';
import {readConnectionCatalog, type ConnectionCatalog, type ConnectionId} from './connection-catalog-api';
import {CONNECTION_GUIDES} from './connection-guides';
import {accountStatusSupported,readConnectionSummary,personalConnectionSummary,type ConnectionSummary} from './connection-summary';
import {useConnectionHealth} from './connection-operation-health';
import {FaxConnectionOverview} from './FaxConnectionOverview';
import {EFaxInboundMount} from './EFaxInboundMount';
import type {EFaxInboundPanelProps} from './EFaxInboundPanel';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';

type Screen = 'home' | 'connections' | 'members' | 'team' | 'core' | 'messaging' | 'payments' | 'portals' | 'scheduling' | 'microsoft' | 'google';
type Editor = Exclude<Screen, 'home' | 'connections'>;
const titles: Record<Screen, string> = {
  home: 'Settings', connections: 'Connections', members:'Practice access', team: 'Your team',
  core: 'Cosmaneura account & appointments', scheduling: 'Scheduling & Google sign-in', microsoft:'Microsoft email & calendar', google:'Google email & calendar',
  messaging: 'Messaging & fax', payments: 'Payments', portals: 'Patient portals',
};

/** Visit editors on demand and retain their recovery/write lifecycle until account exit. */
export function SettingsHub({open, team, members, core, scheduling, microsoft, google, messaging, payments, portals, teamSummary, teamDirty, onClose, navigationLocked = false, initialScreen='home', guidedConnections=false, connectionIdentity, onConnectionAccessLost,onOpenMessagingWork,messagingWorkLabel='Open fax work',messagingWorkBlocked=false,onReviewFaxDocument}: {
  open: boolean; team: ReactNode; members?:ReactNode; core?:ReactNode; scheduling?:ReactNode; microsoft?:ReactNode; google?:ReactNode; messaging?: ReactNode; payments?: ReactNode; portals?: ReactNode;
  teamSummary: string; teamDirty: boolean; onClose: () => void; navigationLocked?: boolean;
  initialScreen?:'home'|'connections'|'core'|'scheduling'|'microsoft'|'google';guidedConnections?:boolean;
  connectionIdentity?:AuthenticatedWorkspaceIdentity;onConnectionAccessLost?:(error:unknown)=>void;
  onOpenMessagingWork?:()=>void;messagingWorkLabel?:string;messagingWorkBlocked?:boolean;onReviewFaxDocument?:EFaxInboundPanelProps['onReviewDocument'];
}) {
  const [screen, setScreen] = useState<Screen>(initialScreen);
  const [inboundBusy,setInboundBusy]=useState(false);
  const leaveLocked=navigationLocked||inboundBusy;
  const [visited, setVisited] = useState<Editor[]>(initialScreen==='core'||initialScreen==='scheduling'||initialScreen==='microsoft'||initialScreen==='google'?[initialScreen]:[]);
  const title = useRef<HTMLHeadingElement>(null);
  const messagingEditor=useRef<HTMLDivElement|null>(null);
  const googleHealth=useConnectionHealth(connectionIdentity,'google'),microsoftHealth=useConnectionHealth(connectionIdentity,'microsoft');
  type Check = {value?:ConnectionSummary; last?:ConnectionSummary; busy:boolean};
  const [directory,setDirectory]=useState<{owner:AuthenticatedWorkspaceIdentity;catalog:ConnectionCatalog|null;error:boolean;busy:boolean;checks:Partial<Record<ConnectionId,Check>>}|null>(null);
  const [refreshCatalog,setRefreshCatalog]=useState(0);
  const accessLost=useRef(onConnectionAccessLost);accessLost.current=onConnectionAccessLost;
  const current=directory?.owner===connectionIdentity?directory:null;
  const catalog=current?.catalog;
  const catalogError=current?.error;
  const checking=!!current&&(current.busy||Object.values(current.checks).some(check=>check.busy));
  const checkingAgain=!!current&&Object.values(current.checks).some(check=>check.last&&(current.busy||check.busy));
  const summaryIds=([['core',core],['google',google],['microsoft',microsoft],['scheduling',scheduling],['messaging',messaging]] as const).filter(([,editor])=>editor!=null).map(([id])=>id).join(',');
  useEffect(()=>{
    if(!open||!['connections','messaging'].includes(screen)||!connectionIdentity)return;
    const controller=new AbortController();const controllers:AbortController[]=[controller];let active=true;
    const catalogTimer=setTimeout(()=>controller.abort(),15000);
    setDirectory(previous=>({owner:connectionIdentity,catalog:previous?.owner===connectionIdentity?previous.catalog:null,
      error:false,busy:true,checks:previous?.owner===connectionIdentity?Object.fromEntries(Object.entries(previous.checks).map(([id,check])=>[id,{last:check.last,busy:false}])):{}}));
    void readConnectionCatalog(connectionIdentity,controller.signal).then(value=>{
      if(!active)return;
      clearTimeout(catalogTimer);
      const ids=summaryIds.split(',').filter(id=>!!id&&(screen!=='messaging'||id==='messaging')) as ConnectionId[];
      setDirectory(previous=>({owner:connectionIdentity,catalog:value,error:false,busy:false,
        checks:Object.fromEntries(Object.keys(value).map(key=>{
          const id=key as ConnectionId,last=previous?.owner===connectionIdentity?previous.checks[id]?.last:undefined;
          const setup:ConnectionSummary={label:'Needs setup',reason:'Your practice administrator needs to finish setup.',action:'View requirements',tone:'attention',checkedAt:Date.now(),checkKind:'availability'};
          return [id,!value[id]?{value:setup,last:setup,busy:false}:{last,busy:ids.includes(id)&&accountStatusSupported(id)}];
        }))}));
      for(const id of ids){
        if(!value[id]||!accountStatusSupported(id))continue;
        const checkController=new AbortController();controllers.push(checkController);
        const timer=setTimeout(()=>checkController.abort(),15000);
        void readConnectionSummary(connectionIdentity,id,checkController.signal).then(result=>{
          if(active)setDirectory(previous=>previous?.owner===connectionIdentity?{...previous,checks:{...previous.checks,[id]:{value:result,last:result,busy:false}}}:previous);
        }).catch(error=>{
          if(!active)return;
          const denied=error instanceof WorkspaceApiError&&(error.status===401||error.status===403&&id!=='core');
          if(denied){
            active=false;controllers.forEach(item=>item.abort());
            setDirectory({owner:connectionIdentity,catalog:null,error:true,busy:false,checks:{}});
            accessLost.current?.(error);return;
          }
          setDirectory(previous=>previous?.owner===connectionIdentity?{...previous,checks:{...previous.checks,[id]:{
            last:previous.checks[id]?.last,busy:false,value:{label:'Needs attention',reason:error instanceof WorkspaceApiError&&error.status===403?'Ask your practice administrator to confirm access.':'Current status is unknown. The latest check failed; open the connection to try again.',action:'Check connection again',tone:'attention'}
          }}}:previous);
        }).finally(()=>clearTimeout(timer));
      }
    }).catch(error=>{
      if(!active)return;
      clearTimeout(catalogTimer);
      const denied=error instanceof WorkspaceApiError&&[401,403].includes(error.status);
      setDirectory(previous=>({owner:connectionIdentity,catalog:null,error:true,busy:false,checks:!denied&&previous?.owner===connectionIdentity?Object.fromEntries(Object.entries(previous.checks).map(([id,check])=>[id,{last:check.last,busy:false}])):{}}));
      if(denied)accessLost.current?.(error);
    });
    return()=>{active=false;clearTimeout(catalogTimer);controllers.forEach(item=>item.abort());};
  },[open,screen,connectionIdentity,refreshCatalog,summaryIds]);
  useEffect(() => { if (!open) setScreen(initialScreen); }, [open,initialScreen]);
  useEffect(() => {
    if(open){setScreen(initialScreen);if(initialScreen==='core'||initialScreen==='scheduling'||initialScreen==='microsoft'||initialScreen==='google')setVisited(previous=>previous.includes(initialScreen)?previous:[...previous,initialScreen]);}
  }, [initialScreen]);
  useEffect(() => {
    if (!open) return;
    title.current?.focus({preventScroll:true});
    title.current?.scrollIntoView?.({block:'start'});
  }, [open, screen]);
  function visit(next: Screen) {
    if (leaveLocked) return;
    if (next !== 'home' && next !== 'connections') {
      if(!(next in CONNECTION_GUIDES)||catalog?.[next as ConnectionId]!==false)
        setVisited(previous => previous.includes(next) ? previous : [...previous, next]);
    }
    setScreen(next);
  }
  const editors = {team, members, core, scheduling, microsoft, google, messaging, payments, portals};
  const connectionCards = (['core','scheduling','google','microsoft','messaging','payments','portals'] as const)
    .filter(id=>editors[id]!=null).map(id=>({id,...CONNECTION_GUIDES[id]}));
  const selectedGuide=screen in CONNECTION_GUIDES?CONNECTION_GUIDES[screen as ConnectionId]:null;
  const setupUnavailable=selectedGuide&&catalog?.[screen as ConnectionId]===false;
  function summary(id:ConnectionId):ConnectionSummary{
    if(current?.busy)return {label:'Not checked',reason:current.checks[id]?.last?'Checking again. Previous results are below.':'Checking your account connection.',action:'Wait for this check or open the connection',tone:'neutral'};
    if(catalogError)return {label:'Needs attention',reason:'Current status is unknown. The latest check failed; try again or open the connection.',action:'Check connection again',tone:'attention'};
    const check=current?.checks[id];
    if(check?.busy)return {label:'Not checked',reason:check.last?'Checking again. Previous results are below.':'Checking your account connection.',action:'Wait for this check or open the connection',tone:'neutral'};
    if(check?.value){
      if(check.value.services&&(id==='google'||id==='microsoft')){
        const health=id==='google'?googleHealth:microsoftHealth;
        return personalConnectionSummary(id,health,check.value.accountVersion===health.accountVersion?check.value.reason:'Account connection changed. Open to review it.');
      }
      return check.value;
    }
    return {label:catalog?.[id]===true?'Available':'Not checked',reason:catalog?.[id]===true?'This service is enabled. Its account and task results have not been checked.':'Account status has not been checked.',action:catalog?.[id]===true?'Review accounts and permissions':'Check connection',tone:'neutral'};
  }
  return <section className="settings-hub" hidden={!open} aria-label="Settings">
    <nav className="settings-hub-nav" aria-label="Settings navigation">
      {screen !== 'home' && <button disabled={leaveLocked} onClick={() => visit(screen === 'members' || screen === 'team' || screen === 'connections' ? 'home' : 'connections')}>
        <span aria-hidden="true">← </span>{screen === 'members' || screen === 'team' || screen === 'connections' ? 'All settings' : 'All connections'}
      </button>}
      <button className="settings-done" disabled={leaveLocked} onClick={onClose}>Done</button>
    </nav>
    {leaveLocked && <p className="settings-navigation-notice" role="status">Wait for this step to finish, or recover any unsaved edits before leaving.</p>}
    <header className={`settings-hub-heading${screen !== 'home' && screen !== 'connections' ? ' settings-hub-heading-quiet' : ''}`}>
      <h1 ref={title} tabIndex={-1}>{titles[screen]}</h1>
      {screen === 'home' && <p>A little setup. A team that fits your practice.</p>}
      {screen === 'connections' && <p>Choose a service, check what is ready, and take the next step.</p>}
    </header>
    {screen === 'home' && <div className="settings-cards">
      <button disabled={navigationLocked} className="settings-card" onClick={() => visit('team')}>
        <span className="settings-card-icon" aria-hidden="true">✳</span>
        <span><strong>Your team</strong><small>{teamSummary}</small>{teamDirty && <em>Unsaved team changes</em>}</span>
        <span aria-hidden="true">›</span>
      </button>
      {members != null && <button disabled={navigationLocked} className="settings-card" onClick={()=>visit('members')}>
        <span className="settings-card-icon" aria-hidden="true">＋</span>
        <span><strong>Practice access</strong><small>Teammates joining your practice workspace</small></span><span aria-hidden="true">›</span>
      </button>}
      {connectionCards.length > 0 && <button disabled={navigationLocked} className="settings-card" onClick={() => visit('connections')}>
        <span className="settings-card-icon" aria-hidden="true">↔</span>
        <span><strong>Connections</strong><small>{core?'Practice account, appointments & services':'Messaging, fax, payments & portals'}</small></span>
        <span aria-hidden="true">›</span>
      </button>}
    </div>}
    {screen === 'connections' && <div className="connection-directory">
      {connectionIdentity&&<div className="connection-directory-status"><p role="status">{checking?(checkingAgain?'Checking again. Last confirmed results remain below.':'Checking connections…'):catalog?'Connected confirms the account. Read results and task outcomes are shown separately.':catalogError?'Connections could not be checked. Try again or open a service.':'Checking connections…'}</p>
        <button disabled={navigationLocked||checking||!catalog&&!catalogError} onClick={()=>setRefreshCatalog(value=>value+1)}>Refresh connections</button></div>}
      <details className="connection-state-help"><summary>What these states mean</summary><dl>
        <div><dt>Available</dt><dd>The feature is enabled. Open it to check the account and task.</dd></div>
        <div><dt>Connected</dt><dd>The account was confirmed. Check each read or task result separately.</dd></div>
        <div><dt>Verified</dt><dd>Both email and calendar reads succeeded for the current account in this session. Task results still need their own review.</dd></div>
        <div><dt>Needs setup</dt><dd>Finish sign-in, account setup or permissions before use.</dd></div>
        <div><dt>Needs attention</dt><dd>A check failed or access needs review. The next action explains how to recover.</dd></div>
        <div><dt>Not checked</dt><dd>No current result is confirmed, or a check is still in progress.</dd></div>
      </dl></details>
      {['Your practice','Email & calendar','Practice services'].map(group=>{
        const cards=connectionCards.filter(item=>item.group===group);return cards.length>0&&<section className="connection-group" key={group} aria-label={group}>
          <h2>{group}</h2><div className="connection-cards">{cards.map(item=>{const state=summary(item.id),fax=state.faxReadiness;
            const canOpenFax=item.id==='messaging'&&!checking&&!catalogError&&catalog?.messaging&&fax?.enabled&&fax.work_enabled&&fax.providers.some(provider=>provider.prepare_enabled_accounts>0);
            return <div className="connection-card-box" key={item.id}><button disabled={navigationLocked||!!connectionIdentity&&!catalog&&!catalogError} className="settings-card connection-card" onClick={()=>visit(item.id)}>
            <span className="settings-card-icon" aria-hidden="true">{item.icon}</span>
            <span className="connection-card-copy"><strong>{titles[item.id]}</strong><small>{state.reason}</small>
              {state.services&&<span className="connection-service-summary">{state.services.map(service=><small key={service.kind}><b>{service.name}:</b> {service.label}
                </small>)}</span>}
            </span>
            <span className="connection-card-state"><span role="status" aria-atomic="true" className={`connection-badge connection-badge-${state.tone}`}>{state.tone==='ready'&&<span aria-hidden="true">✓ </span>}{state.label}</span>
              {!state.checkedAt&&current?.checks[item.id]?.last&&<small>Last confirmed: {current.checks[item.id]!.last!.label}{current.checks[item.id]!.last!.checkedAt?` · ${new Date(current.checks[item.id]!.last!.checkedAt!).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'})}`:''}</small>}
              {!state.action.startsWith('Open ')&&<small className="connection-next-step">Next: {state.action}</small>}
              <span className="connection-card-action">Open {item.id==='core'?'practice connection':item.id==='google'?'Google':item.id==='microsoft'?'Microsoft':item.id==='scheduling'?'Scheduling':item.id==='messaging'?'fax setup':item.id==='payments'?'payments':'portals'} <span aria-hidden="true">›</span></span></span>
          </button>{(state.proof||state.checkedAt||state.services?.some(service=>service.lastSuccessAt))&&<details className="connection-state-help" aria-label={`${titles[item.id]} check details`}>
            <summary>Check details</summary>
            {state.proof&&<p className="connection-proof">{state.proof}</p>}
            {state.checkedAt&&<p>{state.checkKind==='availability'?'Availability checked':'Account checked'} {new Date(state.checkedAt).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'})}</p>}
            {state.services?.filter(service=>service.lastSuccessAt).map(service=><p key={service.kind}>{service.name} · Last successful read: {new Date(service.lastSuccessAt!).toLocaleString(undefined,{dateStyle:'short',timeStyle:'short'})}</p>)}
          </details>}{item.id==='messaging'&&onOpenMessagingWork&&<div className="connection-task-action"><button className="team-primary" disabled={navigationLocked||messagingWorkBlocked||!canOpenFax} onClick={()=>{if(canOpenFax&&!navigationLocked&&!messagingWorkBlocked)onOpenMessagingWork();}}>{messagingWorkLabel}</button><small>Prepare and review a draft. Delivery is checked for each fax.</small></div>}</div>;})}</div>
        </section>;
      })}
      {!connectionCards.length && <p>No connection setup is available for this account.</p>}
      {guidedConnections&&<aside className="connection-next-services"><h2>Other services</h2>
        <p>{ATHENA_CONNECTION_BUILD?'Athena schedule access is managed through your Cosmaneura practice connection.':'Additional EHR connections are managed by your practice.'}</p>
        <p>Connecting an account does not automatically import its contents into a visit or give a bot permission to act.</p>
      </aside>}
    </div>}
    {screen==='messaging'&&connectionIdentity&&<FaxConnectionOverview value={!catalogError&&catalog?.messaging?current?.checks.messaging?.value?.faxReadiness:undefined}
      loading={checking} unavailable={!!setupUnavailable} locked={navigationLocked}
      onRefresh={()=>setRefreshCatalog(value=>value+1)} onSetup={()=>{messagingEditor.current?.focus();messagingEditor.current?.scrollIntoView?.({block:'start'});}}
      onOpenWork={onOpenMessagingWork} workLabel={messagingWorkLabel} workBlocked={messagingWorkBlocked}/>}
    {visited.includes('messaging')&&connectionIdentity&&<div hidden={screen!=='messaging'}><EFaxInboundMount identity={connectionIdentity} locked={navigationLocked} onBusyChange={setInboundBusy} onAuthenticationLost={e=>accessLost.current?.(e)} onReviewDocument={onReviewFaxDocument}/></div>}
    {setupUnavailable&&selectedGuide&&<section className="connection-setup-guide" aria-label="Connection setup steps">
      <span className="connection-badge connection-badge-attention">Needs setup</span><h2>{titles[screen]}</h2><p>{selectedGuide.setup}</p>
      <h3>Your next step</h3><p>Ask your practice administrator to enable this service. No setup request has been sent from this screen.</p>
      <p className="team-fine">Administrator contact: not listed here. Use your practice’s usual support contact.</p>
      <button disabled={navigationLocked} onClick={()=>{setRefreshCatalog(value=>value+1);visit('connections');}}>Check availability again</button>
      <h3>Administrator steps</h3><p>{selectedGuide.setup}</p>
      <details><summary>Your steps after setup</summary><ol>{selectedGuide.steps.filter(step=>!step.startsWith("Have an administrator")).map(step=><li key={step}>{step}</li>)}</ol><p className="connection-access-summary">{selectedGuide.access}</p></details>
    </section>}
    {visited.map(id => <div key={id} ref={id==='messaging'?messagingEditor:undefined} tabIndex={id==='messaging'?-1:undefined} data-settings-screen={id} hidden={screen !== id||!!setupUnavailable}>{editors[id]}</div>)}
  </section>;
}

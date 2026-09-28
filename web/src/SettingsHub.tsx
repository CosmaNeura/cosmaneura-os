import {useEffect, useRef, useState, type ReactNode} from 'react';
import './settings-hub.css';
import {ATHENA_CONNECTION_BUILD} from './AthenaConnectionPanel';
import {readConnectionCatalog, type ConnectionCatalog, type ConnectionId} from './connection-catalog-api';
import {CONNECTION_GUIDES} from './connection-guides';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';

type Screen = 'home' | 'connections' | 'members' | 'team' | 'core' | 'messaging' | 'payments' | 'portals' | 'scheduling' | 'microsoft' | 'google';
type Editor = Exclude<Screen, 'home' | 'connections'>;
const titles: Record<Screen, string> = {
  home: 'Settings', connections: 'Connections', members:'Practice access', team: 'Your team',
  core: 'Cosmaneura account & appointments', scheduling: 'Scheduling & Google sign-in', microsoft:'Microsoft email & calendar', google:'Gmail inbox',
  messaging: 'Messaging & fax', payments: 'Payments', portals: 'Patient portals',
};

/** Visit editors on demand and retain their recovery/write lifecycle until account exit. */
export function SettingsHub({open, team, members, core, scheduling, microsoft, google, messaging, payments, portals, teamSummary, teamDirty, onClose, navigationLocked = false, initialScreen='home', guidedConnections=false, connectionIdentity, onConnectionAccessLost}: {
  open: boolean; team: ReactNode; members?:ReactNode; core?:ReactNode; scheduling?:ReactNode; microsoft?:ReactNode; google?:ReactNode; messaging?: ReactNode; payments?: ReactNode; portals?: ReactNode;
  teamSummary: string; teamDirty: boolean; onClose: () => void; navigationLocked?: boolean;
  initialScreen?:'home'|'connections'|'scheduling'|'microsoft'|'google';guidedConnections?:boolean;
  connectionIdentity?:AuthenticatedWorkspaceIdentity;onConnectionAccessLost?:(error:unknown)=>void;
}) {
  const [screen, setScreen] = useState<Screen>(initialScreen);
  const [visited, setVisited] = useState<Editor[]>(initialScreen==='scheduling'||initialScreen==='microsoft'||initialScreen==='google'?[initialScreen]:[]);
  const title = useRef<HTMLHeadingElement>(null);
  const [catalogState,setCatalogState]=useState<{owner:AuthenticatedWorkspaceIdentity;catalog:ConnectionCatalog|null;error:boolean}|null>(null);
  const [refreshCatalog,setRefreshCatalog]=useState(0);
  const accessLost=useRef(onConnectionAccessLost);accessLost.current=onConnectionAccessLost;
  const catalog=catalogState?.owner===connectionIdentity?catalogState?.catalog:null;
  const catalogError=catalogState?.owner===connectionIdentity&&catalogState?.error;
  useEffect(()=>{
    if(!open||screen!=='connections'||!connectionIdentity)return;
    const controller=new AbortController();let current=true;
    setCatalogState({owner:connectionIdentity,catalog:null,error:false});
    void readConnectionCatalog(connectionIdentity,controller.signal).then(value=>{
      if(current)setCatalogState({owner:connectionIdentity,catalog:value,error:false});
    }).catch(error=>{
      if(!current)return;
      setCatalogState({owner:connectionIdentity,catalog:null,error:true});
      if(error instanceof WorkspaceApiError&&[401,403].includes(error.status))accessLost.current?.(error);
    });
    return()=>{current=false;controller.abort();};
  },[open,screen,connectionIdentity,refreshCatalog]);
  useEffect(() => { if (!open) setScreen(initialScreen); }, [open,initialScreen]);
  useEffect(() => {
    if(open){setScreen(initialScreen);if(initialScreen==='scheduling'||initialScreen==='microsoft'||initialScreen==='google')setVisited(previous=>previous.includes(initialScreen)?previous:[...previous,initialScreen]);}
  }, [initialScreen]);
  useEffect(() => {
    if (!open) return;
    title.current?.focus({preventScroll:true});
    title.current?.scrollIntoView?.({block:'start'});
  }, [open, screen]);
  function visit(next: Screen) {
    if (navigationLocked) return;
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
  return <section className="settings-hub" hidden={!open} aria-label="Settings">
    <nav className="settings-hub-nav" aria-label="Settings navigation">
      {screen !== 'home' && <button disabled={navigationLocked} onClick={() => visit(screen === 'members' || screen === 'team' || screen === 'connections' ? 'home' : 'connections')}>
        <span aria-hidden="true">← </span>{screen === 'members' || screen === 'team' || screen === 'connections' ? 'All settings' : 'All connections'}
      </button>}
      <button className="settings-done" disabled={navigationLocked} onClick={onClose}>Done</button>
    </nav>
    {navigationLocked && <p className="settings-navigation-notice" role="status">Wait for this step to finish, or recover any unsaved edits before leaving.</p>}
    <header className={`settings-hub-heading${screen !== 'home' && screen !== 'connections' ? ' settings-hub-heading-quiet' : ''}`}>
      <h1 ref={title} tabIndex={-1}>{titles[screen]}</h1>
      {screen === 'home' && <p>A little setup. A team that fits your practice.</p>}
      {screen === 'connections' && <p>Connect the accounts your practice uses. You choose what each service can access.</p>}
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
      {connectionIdentity&&<div className="connection-directory-status"><p role="status">{catalog?'Setup availability checked. Open a service to confirm its account connection.':catalogError?'Availability could not be checked. Open a service to review its setup, or try again.':'Checking available services…'}</p>
        <button disabled={navigationLocked||!catalog&&!catalogError} onClick={()=>setRefreshCatalog(value=>value+1)}>Refresh availability</button></div>}
      {['Your practice','Email & calendar','Practice services'].map(group=>{
        const cards=connectionCards.filter(item=>item.group===group);return cards.length>0&&<section className="connection-group" key={group} aria-label={group}>
          <h2>{group}</h2><div className="connection-cards">{cards.map(item=><button disabled={navigationLocked||!!connectionIdentity&&!catalog&&!catalogError} className="settings-card connection-card" key={item.id} onClick={()=>visit(item.id)}>
            <span className="connection-card-top"><span className="settings-card-icon" aria-hidden="true">{item.icon}</span>
              <span className={`connection-badge${catalog?.[item.id]===true?' connection-badge-ready':''}`}>{catalog?.[item.id]===true?'Available':catalog?.[item.id]===false?'Setup needed':connectionIdentity&&!catalogError?'Checking…':'Review setup'}</span></span>
            <span className="connection-card-copy"><strong>{titles[item.id]}</strong><small>{item.description}</small></span>
            <span className="connection-card-action">{catalog?.[item.id]===false?'View setup steps':'Open connection'} <span aria-hidden="true">↗</span></span>
          </button>)}</div>
        </section>;
      })}
      {!connectionCards.length && <p>No connection setup is available for this account.</p>}
      {guidedConnections&&<aside className="connection-next-services"><h2>Other services</h2>
        <p>{ATHENA_CONNECTION_BUILD?'Athena schedule access is managed through your Cosmaneura practice connection.':'Additional EHR connections are managed by your practice.'}</p>
        <p>Connecting an account does not automatically import its contents into a visit or give a bot permission to act.</p>
      </aside>}
    </div>}
    {setupUnavailable&&selectedGuide&&<section className="connection-setup-guide" aria-label="Connection setup steps">
      <span className="connection-badge">Setup needed</span><h2>{titles[screen]}</h2><p>{selectedGuide.setup}</p>
      <h3>How this connection works</h3><ol>{selectedGuide.steps.map(step=><li key={step}>{step}</li>)}</ol>
      <p className="connection-access-summary">{selectedGuide.access}</p>
      <button disabled={navigationLocked} onClick={()=>{setRefreshCatalog(value=>value+1);visit('connections');}}>Check availability again</button>
    </section>}
    {visited.map(id => <div key={id} data-settings-screen={id} hidden={screen !== id||!!setupUnavailable}>{editors[id]}</div>)}
  </section>;
}

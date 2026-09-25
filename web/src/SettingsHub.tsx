import {useEffect, useRef, useState, type ReactNode} from 'react';
import './settings-hub.css';
import {ATHENA_CONNECTION_BUILD} from './AthenaConnectionPanel';

type Screen = 'home' | 'connections' | 'members' | 'team' | 'core' | 'messaging' | 'payments' | 'portals' | 'scheduling' | 'microsoft' | 'google';
type Editor = Exclude<Screen, 'home' | 'connections'>;
const titles: Record<Screen, string> = {
  home: 'Settings', connections: 'Connections', members:'Practice access', team: 'Your team',
  core: 'Cosmaneura account & appointments', scheduling: 'Scheduling & Google sign-in', microsoft:'Microsoft email & calendar', google:'Gmail inbox',
  messaging: 'Messaging & fax', payments: 'Payments', portals: 'Patient portals',
};

/** Visit editors on demand and retain their recovery/write lifecycle until account exit. */
export function SettingsHub({open, team, members, core, scheduling, microsoft, google, messaging, payments, portals, teamSummary, teamDirty, onClose, navigationLocked = false, initialScreen='home', guidedConnections=false}: {
  open: boolean; team: ReactNode; members?:ReactNode; core?:ReactNode; scheduling?:ReactNode; microsoft?:ReactNode; google?:ReactNode; messaging?: ReactNode; payments?: ReactNode; portals?: ReactNode;
  teamSummary: string; teamDirty: boolean; onClose: () => void; navigationLocked?: boolean;
  initialScreen?:'home'|'connections'|'scheduling'|'microsoft'|'google';guidedConnections?:boolean;
}) {
  const [screen, setScreen] = useState<Screen>(initialScreen);
  const [visited, setVisited] = useState<Editor[]>(initialScreen==='scheduling'||initialScreen==='microsoft'||initialScreen==='google'?[initialScreen]:[]);
  const title = useRef<HTMLHeadingElement>(null);
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
      setVisited(previous => previous.includes(next) ? previous : [...previous, next]);
    }
    setScreen(next);
  }
  const editors = {team, members, core, scheduling, microsoft, google, messaging, payments, portals};
  const connectionCards = [
    {id:'core' as const, description:'Confirm your practice, then find your visits'},
    {id:'scheduling' as const, description:'Connect your approved account for appointment scheduling'},
    {id:'google' as const, description:'Connect your account to read Gmail inbox summaries'},
    {id:'microsoft' as const, description:'Connect your account to read Outlook email and upcoming events'},
    {id:'messaging' as const, description:'Spruce, SRFax or Documo'},
    {id:'payments' as const, description:'Stripe payment requests'},
    {id:'portals' as const, description:'Your practice’s existing portal'},
  ].filter(item => editors[item.id] != null);
  return <section className="settings-hub" hidden={!open} aria-label="Settings">
    <nav className="settings-hub-nav" aria-label="Settings navigation">
      {screen !== 'home' && <button disabled={navigationLocked} onClick={() => visit(screen === 'members' || screen === 'team' || screen === 'connections' ? 'home' : 'connections')}>
        <span aria-hidden="true">← </span>{screen === 'members' || screen === 'team' || screen === 'connections' ? 'All settings' : 'All connections'}
      </button>}
      <button className="settings-done" disabled={navigationLocked} onClick={onClose}>Done</button>
    </nav>
    {navigationLocked && <p className="settings-navigation-notice" role="status">Finish saving or recover your edits before leaving this screen.</p>}
    <header className={`settings-hub-heading${screen !== 'home' && screen !== 'connections' ? ' settings-hub-heading-quiet' : ''}`}>
      <h1 ref={title} tabIndex={-1}>{titles[screen]}</h1>
      {screen === 'home' && <p>A little setup. A team that fits your practice.</p>}
      {screen === 'connections' && <p>{guidedConnections?'Start with your practice account. Add the services you use, or return here later.':'Choose the service you want to set up.'}</p>}
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
    {screen === 'connections' && <div className="settings-cards">
      {connectionCards.map(item => <button disabled={navigationLocked} className="settings-card" key={item.id} onClick={() => visit(item.id)}>
        <span><strong>{titles[item.id]}</strong><small>{item.description}</small></span><span aria-hidden="true">›</span>
      </button>)}
      {!connectionCards.length && <p>No connection setup is available for this account.</p>}
      {guidedConnections&&<aside className="connection-next-services"><h2>Other services</h2>
        <p>{ATHENA_CONNECTION_BUILD?'Check an enabled Athena schedule in Cosmaneura account & appointments. Athena access is read-only.':'Outside calendars, EHRs and email will have their own connection steps. Direct setup for these services is not available in this beta build.'}</p>
        {scheduling&&<p>Connect Scheduling above for appointment access.</p>}
        {google&&<p>Connect Gmail above for inbox summaries.</p>}
        {microsoft&&<p>Connect Microsoft above for your Outlook email and calendar.</p>}
        <p>You can continue with your practice account and return to Connections later.</p>
      </aside>}
    </div>}
    {visited.map(id => <div key={id} data-settings-screen={id} hidden={screen !== id}>{editors[id]}</div>)}
  </section>;
}

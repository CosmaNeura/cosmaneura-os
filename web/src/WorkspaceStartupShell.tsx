import type {ReactNode} from 'react';
import './encounter-workspace.css';
import './practice-home.css';

const nav=['Home','Visits and notes','Practice work','Connections','Settings'];

/** Workspace chrome shown while admission checks run. It does not fetch or enable Start. */
export function WorkspaceStartupShell({status,children}:{status:string;children?:ReactNode}){
  return <main className="team-workspace" data-startup-shell="true" aria-label="Workspace">
    <aside className="team-sidebar">
      <div className="team-brand"><span className="team-logo" aria-hidden="true">✳</span>cosmas<span>OS</span></div>
      <p className="team-sidebar-label">YOUR WORKSPACE</p>
      <nav className="practice-navigation" aria-label="Workspace navigation">
        {nav.map(label=><button key={label} type="button" className="team-nav-item" disabled>{label}</button>)}
      </nav>
      <div className="team-sidebar-bottom"><p><span className="team-local-dot"/>Signed-in workspace</p></div>
    </aside>
    <div className="team-main">
      <header className="team-topbar"><span>Provider workspace <span className="team-divider">/</span> Home</span></header>
      {children}
      <section className="practice-home" aria-label="Practice Home">
        <p className="team-kicker">YOUR PRACTICE</p>
        <h1>Let&apos;s get you ready.</h1>
        <p className="practice-home-lead">Record with Scribe or start a private note. Choose a patient or visit later.</p>
        {status&&<p className="practice-home-status" role="status">{status}</p>}
        <form className="practice-quick-start" onSubmit={event=>event.preventDefault()}>
          <label>Note title<input defaultValue="Private note" disabled/></label>
          <div className="practice-home-team"><h2>Your provider team</h2>
            <p>Private drafts first. External actions need separate human review.</p></div>
          <button type="submit" className="team-primary" disabled>Start a private note</button>
          <p className="team-fine">No appointment, email, calendar or patient portal is needed. Patient-linked work and external actions need separate review.</p>
        </form>
      </section>
    </div>
  </main>;
}

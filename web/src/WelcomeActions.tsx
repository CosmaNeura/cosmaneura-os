export function WelcomeActions({showConnections,connectionsDisabled,encounterDisabled,encounterLabel,onConnections,onEncounter,onResearch,compact=false}:{
  showConnections:boolean;connectionsDisabled:boolean;encounterDisabled:boolean;encounterLabel:string;
  onConnections:()=>void;onEncounter:()=>void;onResearch?:()=>void;compact?:boolean;
}) {
  return <div className={`team-welcome-actions${onResearch?' team-welcome-actions-research':''}${compact?' team-welcome-actions-compact':''}`}>
    <button className="team-start-card team-start-card-primary" disabled={encounterDisabled} onClick={onEncounter}>
      <strong>{encounterLabel}</strong><span className="team-start-icon" aria-hidden="true">▤</span>
      <span>Open a visit and pick up your notes.</span><span className="team-start-arrow" aria-hidden="true">↗</span>
    </button>
    {onResearch&&<button className="team-start-card" disabled={connectionsDisabled||encounterDisabled} onClick={onResearch}>
      <strong>Research</strong><span className="team-start-icon" aria-hidden="true">🔎</span>
      <span>Find clinical trials and medical evidence for a visit.</span><span className="team-start-arrow" aria-hidden="true">↗</span>
    </button>}
    {showConnections&&<button className="team-start-card" disabled={connectionsDisabled} onClick={onConnections}>
      <strong>Connect your practice</strong><span className="team-start-icon" aria-hidden="true">↔</span>
      <span>Manage your accounts and services.</span><span className="team-start-arrow" aria-hidden="true">↗</span>
    </button>}
  </div>;
}

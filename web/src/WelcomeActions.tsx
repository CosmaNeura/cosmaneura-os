export function WelcomeActions({showConnections,connectionsDisabled,encounterDisabled,encounterLabel,onConnections,onEncounter,compact=false}:{
  showConnections:boolean;connectionsDisabled:boolean;encounterDisabled:boolean;encounterLabel:string;
  onConnections:()=>void;onEncounter:()=>void;compact?:boolean;
}) {
  return <div className={`team-welcome-actions${compact?' team-welcome-actions-compact':''}`}>
    {showConnections&&<button className="team-start-card" disabled={connectionsDisabled} onClick={onConnections}>
      <strong>Connect your practice</strong><span className="team-start-icon" aria-hidden="true">↔</span>
      <span>Manage your accounts and services.</span><span className="team-start-arrow" aria-hidden="true">↗</span>
    </button>}
    <button className="team-start-card" disabled={encounterDisabled} onClick={onEncounter}>
      <strong>{encounterLabel}</strong><span className="team-start-icon" aria-hidden="true">▤</span>
      <span>Open a visit and pick up your notes.</span><span className="team-start-arrow" aria-hidden="true">↗</span>
    </button>
  </div>;
}

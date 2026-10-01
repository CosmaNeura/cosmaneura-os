import {useState} from 'react';
import {SampleVisit} from './SampleVisit';

export function WelcomeActions({showConnections,connectionsDisabled,encounterDisabled,encounterLabel,onConnections,onEncounter,onResearch,onRecord,onRecording,onChief,compact=false}:{
  showConnections:boolean;connectionsDisabled:boolean;encounterDisabled:boolean;encounterLabel:string;
  onConnections:()=>void;onEncounter:()=>void;onResearch?:()=>void;onRecord?:()=>void;onRecording?:()=>void;onChief?:()=>void;compact?:boolean;
}) {
  const [sample,setSample]=useState(false);
  if(!compact&&onRecord&&onRecording)return <>
    <div className="team-welcome-first-tasks" aria-label="Start with a task">
      {onChief&&<button disabled={encounterDisabled} onClick={onChief}><span className="welcome-task-emoji" aria-hidden="true">🧭</span><strong>Start with Chief</strong><span>Paste a Scribe transcript and summary, or type notes.</span></button>}
      <button disabled={encounterDisabled} onClick={onRecord}><span className="welcome-task-emoji" aria-hidden="true">🎙️</span><strong>Record a visit</strong><span>Choose a visit, confirm consent, then start.</span></button>
      <button disabled={encounterDisabled} onClick={onRecording}><span className="welcome-task-emoji" aria-hidden="true">📄</span><strong>Use an existing recording</strong><span>Review a Scribe conversation with your team.</span></button>
      {!onChief&&<button onClick={()=>setSample(true)}><span className="welcome-task-emoji" aria-hidden="true">🌱</span><strong>Try a sample</strong><span>Practice reviewing a note and team handoffs.</span></button>}
    </div>
    <div className="team-welcome-shortcuts"><button disabled={encounterDisabled} onClick={onEncounter}>Choose an encounter</button>{onChief&&<button onClick={()=>setSample(true)}>🌱 Try a sample</button>}{onResearch&&<button disabled={encounterDisabled} onClick={onResearch}>🔎 Research</button>}{showConnections&&<button disabled={connectionsDisabled} onClick={onConnections}>Connect your practice</button>}</div>
    {sample&&<SampleVisit onClose={()=>setSample(false)}/>}
  </>;
  return <><div className={`team-welcome-actions${onResearch?' team-welcome-actions-research':''}${compact?' team-welcome-actions-compact':''}`}>
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
  </div>{!compact&&<button className="team-subtle" onClick={()=>setSample(true)}>🌱 Try a sample</button>}{sample&&<SampleVisit onClose={()=>setSample(false)}/>}</>;
}

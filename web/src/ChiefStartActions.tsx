import './chief-start-actions.css';

export const CHIEF_STARTERS = [
  {id:'notes',label:'Organize saved notes',prompt:'Organize the saved intake and visit notes into a concise summary. Distinguish documented facts, uncertainties and missing details. Do not create team assignments yet.'},
  {id:'questions',label:'Prepare visit questions',prompt:'Prepare a short visit agenda and questions from the saved notes and sources. Keep unknown facts explicit and identify what the clinician should verify. Do not create team assignments yet.'},
  {id:'team',label:'Prepare team drafts',prompt:'Break down the saved intake and visit notes into useful, independent private draft tasks for the available team members. Preserve source uncertainty and missing facts. Use each teammate only for its actual role, and explain unavailable or dependent work instead of substituting another role. No public search or external action is requested.'},
  {id:'clinical',label:'Plan follow-up and research',prompt:'Use the saved Scribe note and available sources to prepare two drafts: Follow-up’s patient email draft with follow-up instructions and provider action items, and Research’s assessment of drug or treatment questions with supporting sources and further research needed. Flag missing or uncertain details. Keep the work private for my review; do not send an email or run a public search.\n\nMy directions: '},
] as const;

export function ChiefStartActions({locked,modelEnabled,sourceAllowed,hasSavedContext,notesDirty,hasQuestion,canDelegate,compact=false,onChoose}:{
  locked:boolean;modelEnabled:boolean;sourceAllowed:boolean;hasSavedContext:boolean;notesDirty:boolean;hasQuestion:boolean;canDelegate:boolean;
  compact?:boolean;onChoose:(prompt:string)=>void;
}) {
  const disabled=locked||!modelEnabled||!sourceAllowed||!hasSavedContext||notesDirty||hasQuestion;
  const guidance=!modelEnabled?'AI drafting is unavailable. You can still write and review your notes.'
    :!sourceAllowed?'Chief’s saved-source access is off. Review its source choices in Skills & settings.'
    :notesDirty?'Save your notebook changes before preparing a request.'
    :!hasSavedContext?'Save your notes or add a reference note to give Chief context.'
    :hasQuestion?'Your question is below. Keep it, or clear it to choose another task.'
    :'Choose a task, review the question, then send it when ready.';
  return <section className="chief-start-actions" aria-label="Chief task starters">
    <details className={`chief-starters-disclosure${compact?' compact':''}`} open={!compact}>
    <summary>Choose a Chief task</summary>
    <div>{CHIEF_STARTERS.map(task=>{
      const delegationRequired=task.id==='team'||task.id==='clinical';
      return <button type="button" key={task.id} disabled={disabled||delegationRequired&&!canDelegate}
        onClick={()=>{if(!disabled&&(!delegationRequired||canDelegate))onChoose(task.prompt);}}>{task.label}</button>;
    })}</div>
    <p>{guidance}{!canDelegate&&modelEnabled?' Private team assignments are off for Chief.':''}</p>
    </details>
  </section>;
}

export function InitialTeamAction({names,locked,unchanged,onUse,onSettings}:{
  names:string[];locked:boolean;unchanged:boolean;onUse:()=>void;onSettings:()=>void;
}) {
  return <section className="chief-initial-team" aria-label="Start your team">
    <h3>Start your team</h3>
    <p>{unchanged?`${names.join(' · ')}. Use the saved notes and sources you allow. Personalization can wait.`
      :'You have team changes to review. Your notes and settings are retained.'}</p>
    <div>{unchanged&&<button className="team-primary" disabled={locked} onClick={onUse}>Use this team</button>}
      <button disabled={locked} onClick={onSettings}>{unchanged?'Personalize first':'Review team changes'}</button></div>
  </section>;
}

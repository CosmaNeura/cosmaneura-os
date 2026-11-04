import './chief-start-actions.css';
import {ChiefOpenVisit} from './ChiefOpenVisit';

export const CHIEF_STARTERS = [
  {id:'notes',label:'Organize saved notes',prompt:'Organize the saved intake and visit notes into a concise summary. Distinguish documented facts, uncertainties and missing details. Do not create team assignments yet.'},
  {id:'questions',label:'Prepare visit questions',prompt:'Prepare a short visit agenda and questions from the saved notes and sources. Keep unknown facts explicit and identify what the clinician should verify. Do not create team assignments yet.'},
  {id:'team',label:'Prepare team drafts',prompt:'Break down the saved intake and visit notes into useful, independent private draft tasks for the available team members. Preserve source uncertainty and missing facts. Use each teammate only for its actual role, and explain unavailable or dependent work instead of substituting another role. No public search or external action is requested.'},
  {id:'clinical',label:'Plan follow-up and research',prompt:'Use the saved Scribe note and available sources to prepare two drafts: Follow-up’s patient email draft with follow-up instructions and provider action items, and Research’s assessment of drug or treatment questions with supporting sources and further research needed. Flag missing or uncertain details. Keep the work private for my review; do not send an email or run a public search.\n\nMy directions: '},
] as const;

export function ChiefStartActions({locked,modelEnabled,sourceAllowed,hasSavedContext,notesDirty,hasQuestion,canDelegate,visitSummary='',compact=false,minimal=false,reviewSourcesLocked=false,onChoose,onOpenNotebook,onReviewSources}:{
  locked:boolean;modelEnabled:boolean;sourceAllowed:boolean;hasSavedContext:boolean;notesDirty:boolean;hasQuestion:boolean;canDelegate:boolean;
  visitSummary?:string;compact?:boolean;minimal?:boolean;reviewSourcesLocked?:boolean;onChoose:(prompt:string)=>void;onOpenNotebook?:()=>void;onReviewSources?:()=>void;
}) {
  const disabled=locked||!modelEnabled||!sourceAllowed||!hasSavedContext||notesDirty||hasQuestion;
  const sourceReview=modelEnabled&&!sourceAllowed&&onReviewSources?<button className="team-primary" type="button" disabled={locked||notesDirty||reviewSourcesLocked}
    onClick={()=>{if(!locked&&!notesDirty&&!reviewSourcesLocked)onReviewSources();}}>Review source choices</button>:null;
  const guidance=!modelEnabled?'AI drafting is unavailable. You can still write and review your notes.'
    :!sourceAllowed?'Chief’s saved-source access is off. Review its source choices before preparing a task.'
    :notesDirty?'Save your notebook changes before preparing a request.'
    :!hasSavedContext?(visitSummary?`${visitSummary} ${ChiefOpenVisit.notesGap}`:ChiefOpenVisit.missing)
    :hasQuestion?'Your question is below. Keep it, or clear it to choose another task.'
    :`Choose a task, review the question, then send it when ready.${visitSummary?` ${visitSummary}`:''}`;
  if(minimal&&modelEnabled&&sourceAllowed&&!hasSavedContext&&onOpenNotebook)return <section className="chief-start-actions messages-starters" aria-label="Ask Chief on this visit">
    <p>Save notes for this conversation so Chief can help with the next step. Your message draft stays here.</p>
    <button className="team-primary" type="button" disabled={locked} onClick={()=>{if(!locked)onOpenNotebook();}}>Add notes</button>
  </section>;
  if(minimal&&sourceReview)return <section className="chief-start-actions messages-starters" aria-label="Ask Chief on this visit"><p>{guidance}</p>{sourceReview}
    <p>{notesDirty?'Save your notebook changes before opening source choices.':'Your message draft stays here. Only you can change and save these choices.'}</p></section>;
  if(minimal)return <section className="chief-start-actions messages-starters" aria-label="Ask Chief on this visit"><div>{CHIEF_STARTERS.slice(0,2).map(task=><button type="button" key={task.id} disabled={disabled} onClick={()=>{if(!disabled)onChoose(task.prompt);}}>{task.label}</button>)}</div>{disabled&&<p>{guidance}</p>}</section>;
  return <section className="chief-start-actions" aria-label="Ask Chief on this visit">
    <details className={`chief-starters-disclosure${compact?' compact':''}`} open={!compact}>
    <summary>Choose a Chief task</summary>
    <div>{CHIEF_STARTERS.map(task=>{
      const delegationRequired=task.id==='team'||task.id==='clinical';
      return <button type="button" key={task.id} disabled={disabled||delegationRequired&&!canDelegate}
        onClick={()=>{if(!disabled&&(!delegationRequired||canDelegate))onChoose(task.prompt);}}>{task.label}</button>;
    })}</div>
    <p>{guidance}{!canDelegate&&modelEnabled?' Private team assignments are off for Chief.':''}</p>{sourceReview}
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

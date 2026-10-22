import {useEffect,useRef,useState} from 'react';
import {BotAvatar} from './BotAvatar';
import './sample-visit.css';

const source='Jordan: I want to keep track of my sleep routine before our next visit.\nClinician: Bring a one-week sleep diary. We can review it together at follow-up.';
const initialNote='Reason for visit: Discussing sleep routine.\n\nDiscussion: Jordan would like to track sleep before the next visit.\n\nAgreed next step: Bring a one-week sleep diary to follow-up.\n\nDetails to confirm: Visit date and patient details. Date of birth has not been supplied.';

/** A local teaching example; it cannot record, call a model, or save to an encounter. */
export function SampleVisit({onClose}:{onClose:()=>void}) {
  const dialog=useRef<HTMLElement>(null),teamResult=useRef<HTMLElement>(null),[note,setNote]=useState(initialNote),[reviewed,setReviewed]=useState(false),[showTeam,setShowTeam]=useState(false);
  const [followUp,setFollowUp]=useState('Hi Jordan, please bring your one-week sleep diary to our follow-up visit so we can review your sleep routine together.'),[followUpReviewed,setFollowUpReviewed]=useState(false);
  useEffect(()=>{
    const previous=document.activeElement;
    dialog.current?.focus();
    return()=>{if(previous instanceof HTMLElement&&previous.isConnected)previous.focus();};
  },[]);
  useEffect(()=>{if(showTeam){teamResult.current?.scrollIntoView?.({block:'start'});teamResult.current?.focus({preventScroll:true});}},[showTeam]);
  return <div className="sample-visit-backdrop"><section ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="sample-visit-title" className="sample-visit" onKeyDown={event=>{
    if(event.key==='Escape'){event.preventDefault();onClose();}
    if(event.key==='Tab'){
      const controls=Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), textarea:not(:disabled), input:not(:disabled), a[href], summary, [tabindex="0"]')??[]);
      const first=controls[0],last=controls.at(-1);
      if(event.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  }}>
    <header><div><p className="team-kicker">PRACTICE WITH AN INVENTED VISIT</p><h2 id="sample-visit-title">See how your team helps</h2></div><button onClick={onClose} aria-label="Close sample visit">✕</button></header>
    <div className="sample-visit-content">
    <p className="sample-visit-notice">This example works offline. The note and teammate drafts are prepared examples. Your microphone is off, and sample edits stay in this screen.</p>
    <div className="sample-visit-patient"><strong>Jordan Cypress · sample visit</strong><span>Date of birth: not supplied</span></div>
    <p>You can start a real recording without a date of birth. Add it when you have it.</p>
    <details><summary>Read the sample conversation</summary><p className="sample-visit-source">{source}</p></details>
    <section aria-label="Sample note review"><div className="sample-visit-role"><BotAvatar role="scribe"/><div><h3>1. Review Scribe’s note</h3><p>Check the note against the conversation. You can edit it first.</p></div></div>
      <label htmlFor="sample-visit-note">Sample note</label><textarea id="sample-visit-note" value={note} maxLength={5000} onChange={event=>{setNote(event.target.value);setReviewed(false);setShowTeam(false);}}/>
      <label className="sample-visit-check"><input type="checkbox" checked={reviewed} disabled={!note.trim()} onChange={event=>{setReviewed(event.target.checked);if(!event.target.checked)setShowTeam(false);}}/>I checked this sample note against the conversation.</label>
      <button className="team-primary" disabled={!reviewed||!note.trim()} onClick={()=>setShowTeam(true)}>See the sample handoffs</button>
    </section>
    {showTeam&&<section ref={teamResult} tabIndex={-1} aria-label="Sample team handoffs"><div className="sample-visit-role"><BotAvatar role="chief"/><div><h3>2. Chief organizes the next steps</h3><p>These prepared examples use the original sample conversation. Editing this sample does not regenerate them.</p></div></div>
      <ul className="sample-visit-tasks">
        <li><BotAvatar role="visit_prep"/><div><strong>Visit Prep · sample agenda</strong><ol><li>Confirm the visit date and Jordan’s details.</li><li>Review the one-week sleep diary Jordan agreed to bring.</li><li>Ask what Jordan noticed about their sleep routine.</li><li>Agree on next steps together.</li></ol><details><summary>Source for this agenda</summary><p>{source}</p></details></div></li>
        <li><BotAvatar role="research"/><div><strong>Research · optional sample brief</strong><p>Public question: What is a sleep diary?</p><p>A sleep diary records sleep and wake times and related observations. Jordan agreed to bring a week of entries; discuss those observations at follow-up.</p><p><a href="https://www.nhlbi.nih.gov/health/sleep/studies" target="_blank" rel="noreferrer">NHLBI · Sleep studies and sleep diary</a></p><small>Prepared educational example. This screen does not run a search or fetch the reference. A real search requires your reviewed public question.</small></div></li>
        <li><BotAvatar role="follow_up"/><div><strong>Follow-up · sample message draft</strong><label htmlFor="sample-follow-up">Message for Jordan</label><textarea id="sample-follow-up" value={followUp} maxLength={2000} onChange={event=>{setFollowUp(event.target.value);setFollowUpReviewed(false);}}/><label className="sample-visit-check"><input type="checkbox" checked={followUpReviewed} disabled={!followUp.trim()} onChange={event=>setFollowUpReviewed(event.target.checked)}/>I checked this sample message against the agreed next step.</label><p role="status">{followUpReviewed?'Sample message reviewed.':'Needs your review.'}</p><small>Recipient, visit date and delivery channel still need confirmation in a real visit. This sample has no delivery action.</small></div></li>
      </ul><p role="status">{followUpReviewed
        ? 'Sample review complete. In your own visits, check each saved result before using it.'
        : 'One step left: check the follow-up message above.'}</p>
    </section>}
    </div>
    <footer><button onClick={onClose}>{showTeam?'Return to my workspace':'Close sample'}</button></footer>
  </section></div>;
}

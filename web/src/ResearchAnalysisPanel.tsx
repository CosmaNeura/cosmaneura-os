import {useEffect,useRef,useState} from 'react';
import {modelStrip,validConversation} from './model-work-request';
import {researchAnalysisPreview,researchPacketSize,selectedResearchPacket,type ResearchAnalysisDraft,type ResearchEvidenceAnchor} from './research-analysis-contract';
import type {ResearchObservation,ResearchSaved} from './research-contract';
import type {ConversationInput,Workspace} from './workspace-api';

export type ResearchAnalysisAccess={workspace:Workspace;model:{enabled:boolean;model:string};modelBlocked?:boolean;onSubmit:(body:ConversationInput)=>Promise<void>};
export function ResearchAnalysisPanel({access,packet,draft,bot,teamRevision,enabled,locked,run,saved,onEdit,onSubmit,onSmaller,onLoadSources}:{
 access:ResearchAnalysisAccess;packet:ResearchEvidenceAnchor;draft:ResearchAnalysisDraft;bot:string;teamRevision:number;enabled:boolean;locked:boolean;
 onEdit:(draft:ResearchAnalysisDraft)=>void;onSubmit:(body:ConversationInput)=>Promise<void>;onSmaller:()=>void;
 run:ResearchObservation|null;saved:ResearchSaved|null;onLoadSources:()=>void;
}){
 const [open,setOpen]=useState(false),[review,setReview]=useState<ConversationInput|null>(null),[consent,setConsent]=useState(false),[sending,setSending]=useState(false);
 const [proof,setProof]=useState<{signature:string;content:string|null}|null>(null);
 const entry=selectedResearchPacket(access.workspace,packet);
 const proofSignature=JSON.stringify([packet,entry?.content,entry?.source_label,run,saved,bot,access.workspace.id,access.workspace.revision]);
 const content=proof?.signature===proofSignature?proof.content:null,size=content!==null?researchPacketSize([{content}]):'unavailable';
 const available=enabled&&!access.modelBlocked&&access.model.enabled&&!!access.model.model&&size==='ready',blocked=locked||sending;
 const signature=JSON.stringify([proofSignature,content,draft,bot,teamRevision,access.workspace.id,access.workspace.revision,access.model,access.modelBlocked,enabled,locked]);
 const live=useRef(signature),inFlight=useRef(false);live.current=signature;
 useEffect(()=>{let cancelled=false;setProof(null);void researchAnalysisPreview(access.workspace,packet,run,saved,bot).then(content=>{if(!cancelled)setProof({signature:proofSignature,content});});return()=>{cancelled=true;};},[proofSignature]);
 useEffect(()=>{setReview(null);setConsent(false);},[signature]);
 function reviewQuestion(){
  if(blocked||!available||!draft.selected)return;
  const body:ConversationInput={expected_revision:access.workspace.revision,team_revision:teamRevision,idempotency_key:crypto.randomUUID(),role:bot,content:modelStrip(draft.question),research_analysis:{version:1,consented:true,entries:[structuredClone(packet)]}};
  if(!validConversation(body))return;setReview(body);setConsent(false);
 }
 async function send(){
  if(inFlight.current||blocked||!available||!draft.selected||!consent||!review)return;
  const current=signature;inFlight.current=true;setSending(true);
  try{if(live.current===current)await onSubmit(structuredClone(review));}finally{inFlight.current=false;setSending(false);setReview(null);setConsent(false);}
 }
 return <section className="research-analysis" aria-label="Selected source analysis" aria-busy={!!run&&!!saved&&proof?.signature!==proofSignature}>
  <button type="button" className="team-subtle" aria-expanded={open} onClick={()=>setOpen(value=>!value)}>Ask Research about saved sources</button>
  {open&&<div>
   <p>Choose this saved packet and write the question you want the model to answer. Saving sources did not send them to AI.</p>
   {!entry?<p role="status">The saved packet is not available in the current encounter view. Refresh the encounter to verify it.</p>:<>
    <label className="research-select"><input type="checkbox" checked={draft.selected} disabled={blocked||size!=='ready'} onChange={event=>onEdit({...draft,selected:event.target.checked})}/>Use saved source packet · revision {packet.entry_revision}</label>
    {content!==null?<details><summary>Review what Research will receive</summary><p className="research-excerpt">{content}</p><small>{[...content].length.toLocaleString()} characters, including all retained source details · entry {packet.entry_id}</small></details>:<div role="status"><p>Load saved source details before reviewing your AI request. Nothing will be sent until they are verified.</p><button type="button" disabled={blocked} onClick={onLoadSources}>Load saved source details</button></div>}
   </>}
   {size==='too_large'&&<div className="research-status"><p>These retained source details exceed the 5,000-character analysis limit. Select fewer sources and save a smaller packet; nothing will be shortened or sent automatically.</p><button type="button" disabled={blocked||!enabled} onClick={onSmaller}>Choose fewer excerpts to save</button></div>}
   {!access.model.enabled&&<p role="status">AI analysis is not connected. Your saved sources and question remain available.</p>}
   {access.modelBlocked&&<p role="status">AI answers are blocked for this bot. Review its team settings before requesting analysis.</p>}
   <label className="research-question">Question for Research<textarea rows={3} maxLength={4000} value={draft.question} disabled={blocked} onChange={event=>onEdit({...draft,question:event.target.value})} placeholder="For example, compare the findings and explain the uncertainty…"/></label>
   <p className="team-fine">AI analysis is an inference to review, not verification of a source or a clinical decision.</p>
   <button type="button" disabled={blocked||!available||!draft.selected||!modelStrip(draft.question)} onClick={reviewQuestion}>Review AI request</button>
   {review&&<section className="research-query-review" aria-label="Review selected source analysis"><h3>Review this model request</h3><p>{review.content}</p><p>To configured model: <strong>{access.model.model}</strong></p><p>One saved public-source packet · revision {packet.entry_revision}. The source text above includes all retained details and is sent in full.</p>
    <details><summary>What is included</summary><p>Only this question and the selected public sources, including their retained details. No notebook, preparation, work status, other evidence, private conversation history, practice context or bot working preferences.</p><p>Review your question for any information you do not intend to send to the model.</p></details>
    <label><input type="checkbox" checked={consent} disabled={blocked} onChange={event=>setConsent(event.target.checked)}/>I consent to sending this question and retained source details to {access.model.model}.</label>
    <div><button type="button" disabled={blocked} onClick={()=>{setReview(null);setConsent(false);}}>Edit request</button><button type="button" className="team-primary" disabled={blocked||!available||!consent} onClick={()=>void send()}>Send to Research</button></div>
   </section>}
  </div>}
 </section>;
}

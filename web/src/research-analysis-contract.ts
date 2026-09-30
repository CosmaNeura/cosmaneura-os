import {teamClosed,teamHash,teamNatural,teamText,teamUuid} from './team-setup-request';
import type {Workspace,WorkspaceEntry} from './workspace-api';
import type {ResearchObservation,ResearchResult,ResearchSaved} from './research-contract';

export type ResearchEvidenceAnchor={entry_id:string;entry_revision:number;run_id:string;save_request_sha256:string};
export type ResearchAnalysis={version:1;consented:true;entries:ResearchEvidenceAnchor[]};
export type ResearchAnalysisDraft={question:string;selected:boolean};
export function validResearchAnchor(value:unknown):value is ResearchEvidenceAnchor{
 return teamClosed(value,'entry_id,entry_revision,run_id,save_request_sha256')&&teamUuid(value.entry_id)&&teamNatural(value.entry_revision)&&value.entry_revision>=1&&value.entry_revision<=500&&teamUuid(value.run_id)&&teamHash(value.save_request_sha256);
}
export function validResearchAnalysis(value:unknown):value is ResearchAnalysis{
 return teamClosed(value,'version,consented,entries')&&value.version===1&&value.consented===true&&Array.isArray(value.entries)&&value.entries.length>=1&&value.entries.length<=3&&value.entries.every(validResearchAnchor)&&new Set(value.entries.map(entry=>entry.entry_id)).size===value.entries.length;
}
export function validResearchAnalysisDraft(value:unknown):value is ResearchAnalysisDraft{
 return teamClosed(value,'question,selected')&&teamText(value.question,4000)&&typeof value.selected==='boolean';
}
/** Preview only. Public-source proof and current authority are rechecked by the server. */
export function selectedResearchPacket(workspace:Workspace,anchor:ResearchEvidenceAnchor):WorkspaceEntry|null{
 if(!validResearchAnchor(anchor))return null;
 const matches=workspace.entries.filter(entry=>entry.id===anchor.entry_id);
 const entry=matches[0];
 return matches.length===1&&entry.kind==='evidence'&&entry.revision===anchor.entry_revision&&entry.revision<=workspace.revision&&teamText(entry.content,20000)?entry:null;
}
export function researchPacketSize(entries:readonly Pick<WorkspaceEntry,'content'>[]):'ready'|'too_large'|'unavailable'{
 if(entries.length<1||entries.length>3||entries.some(entry=>!teamText(entry.content,131072)))return 'unavailable';
 const lengths=entries.map(entry=>[...entry.content].length);
 return lengths.some(n=>n>5000)||lengths.reduce((a,b)=>a+b,0)>15000||entries.reduce((n,entry)=>n+new TextEncoder().encode(entry.content).length,0)>32768?'too_large':'ready';
}

/** Match the immutable Python source_excerpt format; never rewrite a saved entry. */
export function researchSavedText(records:readonly ResearchResult[]):string{
 return 'Public research source excerpts. Source claims require clinician review.\n\n'+records.map(record=>[
  record.title,record.url,'Source: '+record.source+' / '+record.id,'Retrieved: '+record.retrieved_at,
  'Source updated: '+(record.source_updated_at||'Not supplied'),'Version: '+(record.version||'Not supplied'),
  'Excerpt shortened: '+(record.truncated?'Yes; open the source for full details':'No'),
  'Content SHA-256: '+record.sha256,record.excerpt,
 ].join('\n')).join('\n\n---\n\n');
}

/** Exact analysis_excerpt parity, including empty excerpts and repeated record headers. */
export function researchAnalysisText(records:readonly ResearchResult[]):string{
 if(!records.some(record=>record.fields.length||record.result_scope!=='unknown'))return researchSavedText(records);
 return records.map(record=>{
  const saved=researchSavedText([record]),prefix=record.excerpt?saved.slice(0,-record.excerpt.length):saved;
  return prefix+'\nRetained source details:\nReported result scope: '+record.result_scope+'\n'
   +record.fields.map(field=>field.label+': '+field.text).join('\n')+'\nRetained source excerpt:\n'+record.excerpt;
 }).join('\n\n---\n\n');
}

/** No I/O. Recheck the retained proofs before exposing the complete model passage. */
export async function researchAnalysisPreview(workspace:Workspace,anchor:ResearchEvidenceAnchor,run:ResearchObservation|null,saved:ResearchSaved|null,bot:string):Promise<string|null>{
 try{
  const entry=selectedResearchPacket(workspace,anchor);
  if(!entry||entry.source_label!=='Research · public source excerpts'||!run||!saved)return null;
  const retained=structuredClone({run,saved,entry,anchor}),workspaceId=workspace.id;
  // Import lazily: research-contract also validates durable analysis anchors.
  const {validateResearchObservation,validateResearchSaved}=await import('./research-contract');
  const observation=await validateResearchObservation(retained.run,workspaceId,undefined,bot);
  const receipt=await validateResearchSaved(retained.saved,workspaceId,retained.anchor.run_id,retained.saved.request);
  if(observation.run_id!==receipt.run_id||!['completed','partial'].includes(observation.state)
   ||receipt.entry_id!==retained.anchor.entry_id||receipt.entry_revision!==retained.anchor.entry_revision
   ||receipt.request_sha256!==retained.anchor.save_request_sha256)return null;
  const records=receipt.request.source_hashes.map(hash=>observation.results.find(record=>record.sha256===hash));
  if(records.some(record=>!record))return null;
  const selected=records as ResearchResult[];
  if(researchSavedText(selected)!==retained.entry.content)return null;
  return researchAnalysisText(selected);
 }catch{return null;}
}

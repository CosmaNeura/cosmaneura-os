import {teamClosed,teamHash,teamNatural,teamText,teamUuid} from './team-setup-request';
import type {Workspace,WorkspaceEntry} from './workspace-api';

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
 if(entries.length<1||entries.length>3||entries.some(entry=>!teamText(entry.content,20000)))return 'unavailable';
 const lengths=entries.map(entry=>[...entry.content].length);
 return lengths.some(n=>n>5000)||lengths.reduce((a,b)=>a+b,0)>15000||entries.reduce((n,entry)=>n+new TextEncoder().encode(entry.content).length,0)>32768?'too_large':'ready';
}

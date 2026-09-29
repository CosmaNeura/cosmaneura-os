import type {SessionPrep} from './session-prep-api';
import {teamCanonical, teamClosed, teamHash} from './team-setup-request';

export type SessionPrepAnalysis={version:1;consented:true;brief_id:string;brief_version:number;snapshot_sha256:string};
export function validSessionPrepAnalysis(value:unknown):value is SessionPrepAnalysis {
  return teamClosed(value,'version,consented,brief_id,brief_version,snapshot_sha256')&&value.version===1&&value.consented===true&&
    teamHash(value.brief_id)&&Number.isSafeInteger(value.brief_version)&&Number(value.brief_version)>0&&Number(value.brief_version)<=2147483647&&teamHash(value.snapshot_sha256);
}
/** Called only for a displayed, parsed receipt; no clinical text goes into the command. */
export async function sessionPrepAnalysis(value:SessionPrep):Promise<SessionPrepAnalysis> {
  if(!['ready','refreshing'].includes(value.state)||!value.prepared_brief||!value.brief_id||!value.brief_version)throw new Error('Session Prep is not ready');
  const canonical=teamCanonical(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical));
  return {version:1,consented:true,brief_id:value.brief_id,brief_version:value.brief_version,
    snapshot_sha256:Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('')};
}

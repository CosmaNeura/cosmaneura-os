import {DraftStoreError} from './draft-store';
import type {Workspace,WorkspaceEntry} from './workspace-api';

const UUID=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const MAX_TEXT_BYTES=65536;
export type AnswerCopyData={contract:'chief-answer-copy.v1';entryId:string;contextRevision:number;originalContent:string;content:string};
export const validAnswerCopyText=(value:unknown):value is string=>typeof value==='string'&&new TextEncoder().encode(JSON.stringify(value)).byteLength<=MAX_TEXT_BYTES;

/** A private copy of one completed Chief reply, never a clinical approval or a new request. */
export function canEditAnswerCopy(workspaceId:unknown,entry:WorkspaceEntry):boolean{
  return typeof workspaceId==='string'&&UUID.test(workspaceId)&&UUID.test(entry.id)&&entry.kind==='conversation'&&
    entry.reply?.role==='chief'&&!entry.reply.backend.endsWith('unavailable')&&validAnswerCopyText(entry.reply.content)&&!!entry.reply.content.trim()&&
    Number.isSafeInteger(entry.reply.context_revision)&&entry.reply.context_revision>=0&&
    ![entry.google_source_state,entry.microsoft_source_state,entry.calendar_source_state,entry.fax_source_state,entry.practice_fax_source_state,entry.ehr_source_state,entry.calendar_import_source_state].includes('unavailable');
}
export function parseAnswerCopy(value:unknown,entryId:string):AnswerCopyData{
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).sort().join(',')!=='content,contextRevision,contract,entryId,originalContent')throw new DraftStoreError('integrity');
  const data=value as AnswerCopyData;
  if(data.contract!=='chief-answer-copy.v1'||!UUID.test(entryId)||data.entryId!==entryId||!Number.isSafeInteger(data.contextRevision)||data.contextRevision<0||
    !validAnswerCopyText(data.originalContent)||!data.originalContent.trim()||!validAnswerCopyText(data.content))throw new DraftStoreError('integrity');
  return data;
}
export function answerCopyData(entry:WorkspaceEntry,content:string):AnswerCopyData{
  return parseAnswerCopy({contract:'chief-answer-copy.v1',entryId:entry.id,contextRevision:entry.reply!.context_revision,originalContent:entry.reply!.content,content},entry.id);
}
export function validateAnswerCopySource(data:AnswerCopyData,workspace:Workspace,workspaceId:string):void{
  const entry=workspace.entries.find(item=>item.id===data.entryId);
  if(workspace.id!==workspaceId||!entry||!canEditAnswerCopy(workspaceId,entry)||entry.reply!.content!==data.originalContent||entry.reply!.context_revision!==data.contextRevision)throw new DraftStoreError('integrity');
}

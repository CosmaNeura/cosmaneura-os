import {DraftStoreError} from './draft-store';
import {teamUuid} from './team-setup-request';
import type {ChiefNoteTaskDraft} from './draft-journal';
export type ConversationDraft={text:string;noteTask?:ChiefNoteTaskDraft};
export function parseConversationDraft(value:unknown):ConversationDraft {
  if(!value||typeof value!=='object'||Array.isArray(value))throw new DraftStoreError('integrity');
  const draft=value as ConversationDraft;
  if(Object.keys(draft).some(key=>!['text','noteTask'].includes(key))||typeof draft.text!=='string'||draft.text.length>4000)throw new DraftStoreError('integrity');
  if(draft.noteTask!==undefined){const task=draft.noteTask;
    if(!task||typeof task!=='object'||Array.isArray(task))throw new DraftStoreError('integrity');
    if(Object.keys(task).sort().join(',')!=='content_hash,contract,note_id,note_version,source_fingerprint'||task.contract!=='chief-note-task.compose.v1'||
      !teamUuid(task.note_id)||!Number.isSafeInteger(task.note_version)||task.note_version<1||task.note_version>50||!/^[a-f0-9]{64}$/.test(task.content_hash)||!/^[a-f0-9]{64}$/.test(task.source_fingerprint))throw new DraftStoreError('integrity');}
  return draft;
}


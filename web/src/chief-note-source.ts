import type {Workspace,WorkspaceEntry} from './workspace-api';

export type ChiefNoteOffer={entry:WorkspaceEntry;token:object};
export const supportsChiefNoteSource=(workspace:Pick<Workspace,'note'>):boolean=>
  Array.isArray(workspace.note?.allowed_reply_roles)&&workspace.note.allowed_reply_roles.includes('chief');

/** A completed answer can be offered to the human editor, never saved or approved here. */
export function canReviewChiefNote(entry:WorkspaceEntry,minimumContextRevision=1):boolean{
  const reply=entry.reply;
  return entry.kind==='conversation'&&reply?.role==='chief'&&reply.backend.startsWith('azure_gpt41')&&
    !reply.backend.endsWith('unavailable')&&!!reply.content.trim()&&reply.content.length<=20000&&
    Number.isSafeInteger(reply.context_revision)&&reply.context_revision>=1&&reply.context_revision<entry.revision&&
    Number.isSafeInteger(minimumContextRevision)&&minimumContextRevision>=1&&reply.context_revision>=minimumContextRevision&&
    (!entry.model_request||entry.model_request.admission.state==='completed');
}

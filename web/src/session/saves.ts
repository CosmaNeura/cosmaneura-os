import type {CaptureDraft} from '../capture-notes-api';
import type {AppendInput} from '../workspace-api';
import {clinicalTeamApi} from '../clinical-team-api';
import type {ClinicalNoteShareReceipt} from '../clinical-team-contract';
import {DraftStoreError} from '../draft-store';
import {teamDraft as recoveryTeamDraft,type notebookDraft} from '../draft-journal';
import type {ModelOperation} from '../model-work-request';
import {workspaceApi,WorkspaceApiError,requireRecoveryScope,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace,type WorkspaceIdentity} from '../workspace-api';
import type {PendingSave} from './model';
import type {WorkspaceSession} from './workspace-session';

type WriteApi=Pick<typeof workspaceApi,'saveTeam'|'team'|'append'|'saveNote'|'linkCoreNote'|'reviewNote'|'proposeFollowUp'|'decideFollowUp'|'completeFollowUp'|'link'>;
export type SaveDependencies={workspace?:Partial<WriteApi>;clinical?:Partial<Pick<typeof clinicalTeamApi,'resolve'|'share'>>};
export type SaveContext={
  authenticated?:AuthenticatedWorkspaceIdentity;
  notebookDraft:typeof notebookDraft;
  failure:(cause:unknown)=>void;
  saveModel:(operation:ModelOperation,mode:'submit')=>Promise<void>;
  teamSaved:(team:ProviderTeam)=>void;
  coreNoteLinked:(workspace:Workspace,identity:WorkspaceIdentity,scope:string|undefined)=>void;
};

/** Exact writes and their local durability are independent of the presentation. */
export class WorkspaceSaves {
  private readonly api:WriteApi;
  private readonly clinical:Pick<typeof clinicalTeamApi,'resolve'|'share'>;
  constructor(private readonly session:WorkspaceSession,deps:SaveDependencies={}) {
    this.api=deps.workspace?{...workspaceApi,...deps.workspace}:workspaceApi;this.clinical=deps.clinical?{...clinicalTeamApi,...deps.clinical}:clinicalTeamApi;
  }

  append(kind:AppendInput['kind'],content:string,sourceLabel:string|undefined,context:SaveContext){
    const {workspace,pending,conflict}=this.session.getSnapshot();
    if (!workspace || !content.trim() || pending || conflict) return;
    return this.save({ type: "entry", body: { expected_revision: workspace.revision, idempotency_key: crypto.randomUUID(), kind, content,
      ...(sourceLabel ? { source_label: sourceLabel } : {}) } },context);
  }

  useCoreDraft(draft:CaptureDraft,context:SaveContext){
    const {workspace,busy,pending,conflict}=this.session.getSnapshot();
    if (!workspace || busy || pending || conflict || draft.status !== "draft" || !draft.note_ref || !draft.transcript_ref || !draft.note_sha256) return;
    return this.save({type: "coreNoteLink", body: {expected_revision: workspace.revision, idempotency_key: crypto.randomUUID(),
      base_note_id: workspace.note?.latest?.id ?? null, source: {
        session_id: draft.session_id, scribe_source_id: draft.scribe_source_id, source_sha256: draft.source_sha256,
        schema_ref: draft.schema_ref, transcript_ref: draft.transcript_ref, note_ref: draft.note_ref, note_sha256: draft.note_sha256,
        ...(draft.capture_gap_review ? {capture_gap_review: draft.capture_gap_review} : {}),
        ...(draft.notebook_source ? {notebook_source: draft.notebook_source} : {}),
        ...(draft.reviewed_source ? {reviewed_source: draft.reviewed_source} : {}),
      }}},context);
  }

  async save(operation:PendingSave,context:SaveContext,mode:'submit'|'resolve'='submit',authorityCurrent?:()=>boolean):Promise<ClinicalNoteShareReceipt|undefined> {
    if(operation.type==='ask'||operation.type==='retry'){await context.saveModel(operation,'submit');return;}
    const session=this.session,{identity,workspace,team,note,thought,evidence,source,busy,pending,recoveryOffers,recoveryState}=session.getSnapshot();
    const {authenticated,notebookDraft}=context,access=authenticated||identity;
    if(!access||busy||(operation.type!=='team'&&(!workspace||!identity))||authorityCurrent&&!authorityCurrent())return;
    const current=session.generation.current,currentSave=()=>current===session.generation.current&&(!authorityCurrent||authorityCurrent());
    const {journal}=session.recovery;
    session.setPending(operation);session.setBusy(true);session.setError('');session.setMessage('');
    if(operation.type==='clinicalNoteShare')session.setClinicalShareCheck(null);
    let transmitted=false,confirmedShare:ClinicalNoteShareReceipt|undefined;
    try {
      const active=journal.current?.value;
      if(authenticated) {
        const scope=requireRecoveryScope(team);
        if(!active||journal.current?.serverScope!==scope||recoveryOffers.some(offer=>offer.address===(operation.type==='team'?'team':`workspace:${workspace?.id}`))||recoveryState==='failed')throw new Error('Device draft recovery unavailable');
        if(operation.type==='team'&&team)await active.persist('team',recoveryTeamDraft(team,operation.body.configuration,operation));
        else if(workspace)await active.persist(`workspace:${workspace.id}`,notebookDraft(workspace,note,thought,evidence,source,operation));
        if(!currentSave())return;
      }
      transmitted=true;
      if(operation.type==='team') {
        const result=await this.api.saveTeam(access,operation.body);if(!currentSave())return;
        session.recovery.checkOwner(authenticated,result);
        // A committed idempotent receipt may precede the current configuration.
        const latest=await this.api.team(access);if(!currentSave())return;
        session.recovery.checkOwner(authenticated,latest);
        if(latest.revision<result.revision)throw new WorkspaceApiError(503);
        if(active)await active.persist('team',null);if(!currentSave())return;
        session.setTeam(latest);session.setTeamDraft(structuredClone(latest.configuration));context.teamSaved(latest);
        session.setMessage(`Team settings saved · revision ${result.revision}.${latest.revision!==result.revision?` Current team revision ${latest.revision} is shown.`:''}`);
      } else {
        if(!workspace||!identity)return;
        let result:{workspace:Workspace;entry_revision:number};
        if(operation.type==='clinicalNoteShare') {
          if(!authenticated)throw new WorkspaceApiError(401);
          const receipt=await this.clinical[mode==='resolve'?'resolve':'share'](authenticated,workspace.id,operation.body);
          if(!currentSave())return;
          if(receipt.outcome==='not_found') {
            session.setClinicalShareCheck({operation,receipt,owner:identity,generation:current});
            session.setMessage(receipt.workspace.revision>operation.body.expected_revision?
              'This note share was not saved, and the notebook has advanced. Close this rejected request, then review the current saved note.':
              'This exact note share was not found. You can retry the same saved request.');return;
          }
          result={workspace:receipt.workspace,entry_revision:receipt.source_entry_revision!};confirmedShare=receipt;
        } else result=operation.type==='entry'?await this.api.append(identity,workspace.id,operation.body):
          operation.type==='note'?await this.api.saveNote(identity,workspace.id,operation.body):
          operation.type==='coreNoteLink'?await this.api.linkCoreNote(identity,workspace.id,operation.body):
          operation.type==='review'?await this.api.reviewNote(identity,workspace.id,operation.noteId,operation.body):
          operation.type==='followUpPropose'?await this.api.proposeFollowUp(identity,workspace.id,operation.body):
          operation.type==='followUpDecision'?await this.api.decideFollowUp(identity,workspace.id,operation.ticketId,operation.body):
          operation.type==='followUpComplete'?await this.api.completeFollowUp(identity,workspace.id,operation.ticketId,operation.body):
          await this.api.link(identity,workspace.id,operation.body);
        if(!currentSave())return;
        if(active)await active.persist(`workspace:${workspace.id}`,notebookDraft(result.workspace,note,
          operation.type==='entry'&&operation.body.kind==='conversation'?'':thought,
          operation.type==='entry'&&operation.body.kind==='evidence'?'':evidence,
          operation.type==='entry'&&operation.body.kind==='evidence'?'':source,null));
        if(!currentSave())return;
        session.setWorkspace(result.workspace);
        if(operation.type==='coreNoteLink')context.coreNoteLinked(result.workspace,identity,journal.current?.scope);
        if(operation.type==='entry'&&operation.body.kind==='conversation')session.setThought('');
        if(operation.type==='entry'&&operation.body.kind==='evidence'){session.setEvidence('');session.setSource('');}
        session.setMessage(operation.type==='clinicalNoteShare'?'This exact saved note is shared with your private team. Ask Chief when you are ready.':`Saved revision ${result.entry_revision}.`);
      }
      session.setPending(null);session.setConflict(false);return confirmedShare;
    } catch(cause) {if(currentSave()) {
      if(!transmitted){if(!pending)session.setPending(null);session.setRecoveryState('failed');session.setError("The request was not sent. Recheck this device's draft storage before saving.");}
      else if(operation.type==='clinicalNoteShare'&&!(cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status)))
        session.setError('The note share could not be confirmed. Its exact request is retained; check the saved result before continuing.');
      else context.failure(cause);
    }} finally {if(currentSave())session.setBusy(false);}
  }

  async closeRejectedClinicalShare(context:Pick<SaveContext,'authenticated'|'notebookDraft'>):Promise<void> {
    const session=this.session,{busy,clinicalShareCheck:checked,pending,identity,team,note,thought,evidence,source}=session.getSnapshot();
    if(busy||!checked||pending!==checked.operation||checked.owner!==identity||checked.generation!==session.generation.current||
      checked.receipt.outcome!=='not_found'||checked.receipt.workspace.revision<=checked.operation.body.expected_revision)return;
    const current=session.generation.current,{journal}=session.recovery,active=journal.current?.value;session.setBusy(true);
    try {
      if(context.authenticated&&(!active||journal.current?.serverScope!==requireRecoveryScope(team)))throw new DraftStoreError('unavailable');
      // An absent request at an advanced monotonic revision cannot be admitted later.
      await active?.persist(`workspace:${checked.receipt.workspace.id}`,context.notebookDraft(checked.receipt.workspace,note,thought,evidence,source,null));
      if(current!==session.generation.current)return;
      session.setWorkspace(checked.receipt.workspace);session.setPending(null);session.setClinicalShareCheck(null);session.setError('');
      session.setMessage('Rejected note share closed. Your working text is retained; review the current saved note before sharing again.');
    } catch {if(current===session.generation.current){session.setRecoveryState('failed');session.setError('The rejected request is retained. Recheck local recovery before continuing.');}}
    finally {if(current===session.generation.current)session.setBusy(false);}
  }
}

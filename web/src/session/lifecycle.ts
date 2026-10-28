import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type WorkspaceIdentity} from '../workspace-api';
import {workspaceProtocolGeneration,workspaceProtocolPhase} from '../workspace-protocol';
import type {WorkspaceSession} from './workspace-session';

/** Transitional ports for slices still owned by the workspace host. */
export type LifecycleContext = {
  authenticated?:AuthenticatedWorkspaceIdentity;
  connectionRecovery?:{identity:WorkspaceIdentity;phase:string}|null;
  clear:()=>void;
  recoveryFailed:()=>void;
  invalidateSetup:()=>void;
};

export type LifecycleDependencies = {
  checkSyntheticConnection:()=>Promise<unknown>;
  protocolPhase:(owner:WorkspaceIdentity)=>string;
  protocolGeneration:(owner:WorkspaceIdentity)=>number;
};

/** Connection recovery never submits a retained write or adopts private data. */
export class WorkspaceLifecycle {
  private readonly deps:LifecycleDependencies;
  constructor(private readonly session:WorkspaceSession,deps:Partial<LifecycleDependencies>={}) {
    this.deps={checkSyntheticConnection:()=>workspaceApi.checkSyntheticConnection(),
      protocolPhase:workspaceProtocolPhase,protocolGeneration:workspaceProtocolGeneration,...deps};
  }

  transientConnectionFailure(cause:unknown,context:LifecycleContext):boolean {
    if(!(cause instanceof WorkspaceApiError)||cause.status!==503||cause.code!=='workspace_protocol_required')return false;
    const owner=context.authenticated??this.session.getSnapshot().identity;
    // A pre-reconnect reply cannot restore a warning after recovery completes.
    if(owner&&(this.deps.protocolPhase(owner)!=='ready'||
      context.connectionRecovery?.identity===owner&&context.connectionRecovery.phase!=='ready'))
      this.session.setConnectionError({identity:owner,generation:this.deps.protocolGeneration(owner),message:cause.message});
    return true;
  }

  failure(cause:unknown,context:LifecycleContext,retry?:()=>Promise<void>):void {
    if(this.transientConnectionFailure(cause,context))return;
    const session=this.session;
    session.setMessage('');
    if(cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status)) {
      context.clear();
      session.setError(cause.status===426?
        'Update required for this team configuration. Private content is withheld; encrypted drafts and exact unconfirmed requests remain on this device.':
        'Workspace access is unavailable. Private content has been cleared from this view.');
    } else {
      if(cause instanceof WorkspaceApiError&&cause.code==='workspace_recovery_unavailable')context.recoveryFailed();
      session.setError(cause instanceof WorkspaceApiError?cause.message:'The request could not be confirmed. Retry when the local service is available.');
      if(retry)session.setReadRetry({run:retry});
      if(cause instanceof WorkspaceApiError&&cause.status===409) {
        session.setConflict(true);session.setPending(null);context.invalidateSetup();
      }
      if(cause instanceof WorkspaceApiError&&[400,422].includes(cause.status))session.setPending(null);
    }
  }

  modelFailure(cause:unknown,context:LifecycleContext):void {
    if(this.transientConnectionFailure(cause,context))return;
    if(cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status)) {
      this.failure(cause,context);return;
    }
    this.session.setError(cause instanceof WorkspaceApiError?cause.message:
      'The model request could not be confirmed. Its exact request is retained; check the saved result.');
  }

  async recheckSyntheticConnection(context:LifecycleContext,navigationLocked:boolean):Promise<void> {
    const session=this.session,{identity,busy,pending}=session.getSnapshot();
    if(context.authenticated||identity||busy||pending||navigationLocked)return;
    const current=session.generation.current;session.setBusy(true);session.setError('');
    try {
      await this.deps.checkSyntheticConnection();
      if(current===session.generation.current)session.setMessage('Your workspace service is available. Open a synthetic encounter to continue.');
    } catch(cause) {
      if(current===session.generation.current)this.failure(cause,context,()=>this.recheckSyntheticConnection(context,navigationLocked));
    } finally {if(current===session.generation.current)session.setBusy(false);}
  }
}

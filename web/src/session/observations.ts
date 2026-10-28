import {modelActive} from '../model-work-request';
import {workspaceApi,WorkspaceApiError,type WorkspaceIdentity,type Workspace} from '../workspace-api';
import type {WorkspaceSession} from './workspace-session';
export type ObservationContext={visible:()=>boolean;subscribeVisibility:(changed:()=>void)=>()=>void;modelFailure:(cause:unknown)=>void};

/** Background observations follow one session and pause when its host is hidden. */
export class WorkspaceObservations {
  readonly fastOwner:{current:{identity:WorkspaceIdentity|null;workspaceId:string}|null}={current:null};
  constructor(private readonly session:WorkspaceSession,private readonly read:typeof workspaceApi.read=(...args)=>workspaceApi.read(...args)){}
  watch(context:ObservationContext):(()=>void)|undefined {
    const {workspace,identity,busy,conflict,handoffReviewPending}=this.session.getSnapshot();
    const {setConflict,setError,setWorkspace,generation}=this.session;
    const current=generation.current,fastObservationOwner=this.fastOwner,{modelFailure}=context;
    if (!workspace || !identity || busy || conflict || handoffReviewPending || !(workspace.entries.some(modelActive)||workspace.handoffs?.some(h =>
      ["queued", "running"].includes(h.status) || (h.result_entry_id && !workspace.entries.some(e => e.id === h.result_entry_id))))) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>|undefined,reading=false,controller:AbortController|null=null;
    const visible=()=>current===generation.current&&context.visible();
    const poll = async () => {
      if(cancelled||reading||!visible())return;
      reading=true;controller=new AbortController();
      fastObservationOwner.current={identity,workspaceId:workspace.id};
      try {
        const latest = await this.read(identity, workspace.id,controller.signal);
        if (cancelled||controller.signal.aborted||!visible()||current!==generation.current) return;
        if(latest.id!==workspace.id||latest.revision<workspace.revision)throw new WorkspaceApiError(503);
        const noteRevision = (value: Workspace) => value.entries.filter(e => e.kind === "scratchpad").at(-1)?.revision ?? 0;
        if (noteRevision(latest) !== noteRevision(workspace)) {
          setConflict(true); setError("The saved notebook changed while your bot was working. Load the latest version to compare it with your unsaved text.");
        }
        setWorkspace(latest);
      } catch (cause) { if (!cancelled&&!controller.signal.aborted&&visible()&&current===generation.current) modelFailure(cause); }
      finally{
        reading=false;
        if (!cancelled&&visible()) {
          const delay=foregroundRequested?0:5000;foregroundRequested=false;
          timer = setTimeout(poll,delay);
        }
      }
    };
    // Reuse a healthy in-flight observation. If returning while an aborted
    // hidden read settles, request one immediate read after its settlement.
    let foregroundRequested = false;
    const foreground=()=>{
      clearTimeout(timer);
      if(!visible()){foregroundRequested=false;controller?.abort();return;}
      if(reading){foregroundRequested=controller?.signal.aborted===true;return;}
      foregroundRequested=false;void poll();
    };
    const removeVisibility=context.subscribeVisibility(foreground);
    // Surface short completions sooner; unchanged repeats remain bounded at five seconds.
    if(visible())timer=setTimeout(poll,fastObservationOwner.current?.identity===identity&&fastObservationOwner.current.workspaceId===workspace.id?5000:2000);
    return () => { cancelled = true; clearTimeout(timer);controller?.abort();removeVisibility(); };
  }
}

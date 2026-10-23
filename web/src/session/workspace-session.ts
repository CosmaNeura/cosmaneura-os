import type {StateUpdate, WorkspaceSessionSnapshot, WorkspaceSessionState} from './model';

/**
 * One owner for session state, shared by every presentation.
 *
 * Feature controllers are extracted into this owner incrementally. The epoch
 * supplements operation, route and authority guards; it does not replace them.
 */
export class WorkspaceSession {
  private snapshot: WorkspaceSessionSnapshot = Object.freeze({
    identity:null,connectionError:null,busy:false,pending:null,conflict:false,
    message:'',error:'',readRetry:null,
  });
  private readonly listeners = new Set<()=>void>();

  // Kept as one stable cell while existing async closures move out of the view.
  readonly generation = {current:0};

  readonly getSnapshot = ():WorkspaceSessionSnapshot => this.snapshot;
  readonly subscribe = (listener:()=>void):(()=>void) => {
    this.listeners.add(listener);
    return ()=>{this.listeners.delete(listener);};
  };

  readonly setIdentity = this.setter('identity');
  readonly setConnectionError = this.setter('connectionError');
  readonly setBusy = this.setter('busy');
  readonly setPending = this.setter('pending');
  readonly setConflict = this.setter('conflict');
  readonly setMessage = this.setter('message');
  readonly setReadRetry = this.setter('readRetry');

  readonly setError = (error:string):void => {
    this.patch({error,readRetry:null});
  };

  readonly invalidate = ():void => {this.generation.current++;};

  private setter<K extends keyof WorkspaceSessionState>(key:K) {
    return (update:StateUpdate<WorkspaceSessionState[K]>):void => {
      const value=typeof update==='function'
        ? (update as (previous:WorkspaceSessionState[K])=>WorkspaceSessionState[K])(this.snapshot[key])
        : update;
      this.patch({[key]:value} as Pick<WorkspaceSessionState,K>);
    };
  }

  private patch(update:Partial<WorkspaceSessionState>):void {
    const keys=Object.keys(update) as (keyof WorkspaceSessionState)[];
    if(keys.every(key=>Object.is(this.snapshot[key],update[key])))return;
    this.snapshot=Object.freeze({...this.snapshot,...update});
    for(const listener of [...this.listeners])listener();
  }
}

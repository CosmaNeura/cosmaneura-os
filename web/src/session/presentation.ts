import type {WorkspaceSession} from './workspace-session';

export type Presentation='workspace'|'messages';
export const PRESENTATION_KEY='cosmas.presentation.v1';
export type PresentationOptions={enabled:boolean;phone:boolean;storage?:Pick<Storage,'getItem'|'setItem'>};
export class WorkspacePresentationPreference {
  private readonly storage?:PresentationOptions['storage'];
  readonly enabled:boolean;
  readonly phone:boolean;
  constructor(private readonly session:WorkspaceSession,options:PresentationOptions={enabled:false,phone:false}){
    this.storage=options.storage;this.enabled=options.enabled;this.phone=options.phone;
    try{const saved=this.storage?.getItem(PRESENTATION_KEY);if(saved==='workspace'||saved==='messages')session.setPresentationPreference(saved);}catch{/* Default until the device preference can be read. */}
  }
  current():Presentation {
    if(!this.enabled||!this.session.getSnapshot().team?.revision)return 'workspace';
    return this.session.getSnapshot().presentationPreference??(this.phone?'messages':'workspace');
  }
  choose(value:Presentation,transitionBlocked:boolean):boolean {
    const state=this.session.getSnapshot();
    if(!this.enabled||!state.team?.revision||transitionBlocked||state.busy||state.pending||state.conflict||state.clinicalPreparing||state.conversationBusy||state.recordingTransition||state.researchPending||state.handoffReviewPending||state.recoveryState==='failed'||state.recoveryOffers.length||!['workspace','messages'].includes(value))return false;
    try{if(!this.storage)throw new Error();this.storage.setItem(PRESENTATION_KEY,value);}
    catch{this.session.setPresentationError('This layout preference could not be saved on this device. Try again.');return false;}
    this.session.setPresentationError('');this.session.setPresentationPreference(value);return true;
  }
}

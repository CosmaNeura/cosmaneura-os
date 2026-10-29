import {botAddress,supportsSkill,type ProviderTeam,type Workspace} from '../workspace-api';
import {researchAnalysisPreview,selectedResearchPacket,type ResearchEvidenceAnchor} from '../research-analysis-contract';
import type {ResearchObservation,ResearchSaved} from '../research-contract';
import type {ConversationHost} from './conversations';
import type {WorkspaceSession} from './workspace-session';
class ResearchChiefError extends Error {}

/** Existing immutable Research proofs, kept in memory only; never copied into the composer. */
export type ResearchChiefSelection={workspace_id:string;workspace_revision:number;team_revision:number;bot:string;
  anchor:ResearchEvidenceAnchor;run:ResearchObservation;saved:ResearchSaved};
export function researchChiefUnavailable(team:ProviderTeam|null):string|null{
  const chiefs=team?.configuration.bots.filter(bot=>bot.role==='chief'&&!bot.retired)??[];
  if(chiefs.length!==1||!chiefs[0].enabled)return 'Chief is unavailable. Your saved Research packet is kept.';
  const chief=chiefs[0];
  if(chief.blocked_capabilities?.includes('model_answer'))return 'Chief’s AI answers are paused in team settings. Your saved Research packet is kept.';
  if(!supportsSkill(chief,'saved_context')||!chief.include_evidence)return 'Allow Chief to use saved evidence in team settings before preparing this draft.';
  return null;
}
const packetSignature=(workspace:Workspace,anchor:ResearchEvidenceAnchor)=>{
  const entry=selectedResearchPacket(workspace,anchor);
  return entry?JSON.stringify([entry.id,entry.revision,entry.source_label,entry.content]):null;
};
export function researchChiefDirections(anchor:ResearchEvidenceAnchor):string{
  return `Review the saved public Research packet ${anchor.entry_id} (revision ${anchor.entry_revision}) when planning the next step. Keep source claims, coverage and uncertainty separate from clinical conclusions. Ask me about missing details before proposing outside actions.`;
}

/** Draft-only continuation. Research's source-isolated model contract stays Research-only. */
export class ResearchChiefHandoff {
  private preparing=false;
  constructor(private readonly session:WorkspaceSession,private readonly prove=researchAnalysisPreview){}
  async prepare(selection:ResearchChiefSelection,host:ConversationHost,focus:()=>void):Promise<boolean>{
    const origin=this.session.getSnapshot(),originGeneration=this.session.generation.current,originRoute=this.session.navigation.sequence.current;
    const originEdit=this.session.models.thoughtEditVersion.current;
    if(this.preparing||!host.current()||host.blocked()||!origin.workspace?.appointment_id||origin.practicePage!=='notebook'||origin.settingsOpen||origin.practiceOpen||
      this.session.recovery.journal.current?.value!==host.journal||this.session.recovery.journal.current.scope!==host.scope||
      selection.workspace_id!==origin.workspace.id||selection.workspace_revision!==origin.workspace.revision||selection.team_revision!==origin.team?.revision||
      selection.bot!==origin.selected||!origin.team.configuration.bots.some(bot=>botAddress(bot)===selection.bot&&bot.role==='research'))return false;
    const id=origin.workspace.id,appointment=origin.workspace.appointment_id,teamRevision=origin.team.revision;
    const owned=()=>host.current()&&this.session.recovery.journal.current?.value===host.journal&&this.session.recovery.journal.current.scope===host.scope;
    const scoped=()=>{const live=this.session.getSnapshot();return owned()&&live.workspace?.id===id&&live.workspace.appointment_id===appointment&&live.team?.revision===teamRevision;};
    let current=()=>scoped()&&this.session.generation.current===originGeneration&&this.session.navigation.sequence.current===originRoute&&this.session.models.thoughtEditVersion.current===originEdit&&this.session.getSnapshot().selected===selection.bot;
    let busyGeneration:number|null=null;
    this.preparing=true;
    try{
      const selected=structuredClone(selection),unavailable=researchChiefUnavailable(origin.team);
      if(unavailable)throw new ResearchChiefError(unavailable);
      const signature=packetSignature(origin.workspace,selected.anchor);
      if(!signature||await this.prove(origin.workspace,selected.anchor,selected.run,selected.saved,selected.bot)===null)throw new ResearchChiefError('The saved Research packet could not be verified. Check its saved source details before preparing Chief.');
      if(!current()||host.blocked()||packetSignature(this.session.getSnapshot().workspace!,selected.anchor)!==signature)return false;
      const chief=origin.team.configuration.bots.find(bot=>bot.role==='chief'&&!bot.retired)!;
      if(!await this.session.conversations.prepareSourceDraft(id,botAddress(chief),host))return false;
      const generation=this.session.generation.current,route=this.session.navigation.sequence.current,edit=this.session.models.thoughtEditVersion.current;
      const destination=()=>scoped()&&generation===this.session.generation.current&&route===this.session.navigation.sequence.current&&this.session.getSnapshot().selected===botAddress(chief)&&this.session.getSnapshot().practicePage==='notebook'&&!this.session.getSnapshot().settingsOpen&&!this.session.getSnapshot().practiceOpen;
      current=()=>destination()&&this.session.models.thoughtEditVersion.current===edit;
      if(!current()||host.blocked())return false;
      if(this.session.getSnapshot().phoneNoteTask)throw new ResearchChiefError('Finish or close the saved-note draft in Chief first. Its directions and your Research packet are kept.');
      const fresh=this.session.getSnapshot().workspace!;
      if(packetSignature(fresh,selected.anchor)!==signature||await this.prove(fresh,selected.anchor,selected.run,selected.saved,selected.bot)===null)throw new ResearchChiefError('The saved Research packet changed. Check its saved source details before preparing Chief.');
      if(!current()||host.blocked())return false;
      busyGeneration=generation;this.session.setConversationBusy(true);
      await host.authorize();
      if(!current()||host.blocked())return false;
      const live=this.session.getSnapshot(),reason=researchChiefUnavailable(live.team);
      if(reason)throw new ResearchChiefError(reason);
      if(packetSignature(live.workspace!,selected.anchor)!==signature)throw new ResearchChiefError('The saved Research packet changed. Your Chief draft is kept.');
      const prompt=researchChiefDirections(selected.anchor),before=live.thought;
      const next=before.endsWith(prompt)?before:before.trim()?before+'\n\n'+prompt:prompt;
      if(next.length>4000)throw new ResearchChiefError('Chief’s draft is too long to add these directions. Shorten it before preparing the Research packet; no text was removed.');
      const accepts=()=>current()&&!host.blocked()&&!researchChiefUnavailable(this.session.getSnapshot().team)&&packetSignature(this.session.getSnapshot().workspace!,selected.anchor)===signature;
      if(!await this.session.conversations.appendPreparedDraft(next,host,accepts))return false;
      const appended=this.session.models.thoughtEditVersion.current;
      current=()=>destination()&&this.session.models.thoughtEditVersion.current===appended;
      if(!current())return false;
      this.session.setSelectedResult(null);this.session.setSelectedSource(selected.anchor.entry_id);this.session.setSavedResearchChat(false);
      this.session.setMobilePanel('Conversation');focus();return true;
    }catch(cause){if(current())this.session.setError(cause instanceof ResearchChiefError?cause.message:'The Chief draft could not be confirmed. Reopen its private draft before continuing; nothing was sent.');return false;}
    finally{this.preparing=false;if(busyGeneration!==null&&busyGeneration===this.session.generation.current)this.session.setConversationBusy(false);}
  }
}

import {botAddress,type BotSettings,type Workspace} from '../workspace-api';
import type {SaveContext} from './saves';
import type {WorkspaceSession} from './workspace-session';

export const latestNotebookText=(workspace:Workspace|null)=>workspace?.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'';
export function hasSavedBotContext(workspace:Workspace|null,bot:BotSettings|undefined):boolean {
  return !!bot&&!!workspace?.entries.some(entry=>entry.content.trim()&&
    (entry.kind==='scratchpad'&&entry.content===latestNotebookText(workspace)&&bot.include_notebook||
      (entry.kind==='evidence'||entry.kind==='synthetic_source'||
        entry.kind==='google_message'&&entry.google_source_state==='current'||entry.kind==='google_calendar'&&entry.calendar_source_state==='current'||
        entry.kind==='efax_inbound_source'&&entry.fax_source_state==='current'||entry.kind==='fax_inbound_source'&&entry.practice_fax_source_state==='current'||entry.kind==='ehr_read_source'&&entry.ehr_source_state==='current'||entry.kind==='calendar_import_source'&&entry.calendar_import_source_state==='current')&&bot.include_evidence));
}
export type ComposerContext={locked:boolean;connectionNavigationLocked:boolean;captureNavigationLocked:boolean;captureDraftLocked:boolean;recoveryBlocked:boolean;focus:()=>void;closeTools:()=>void;save:SaveContext};

/** Intent survives presentation changes; continuations use the exact saved notes. */
export class WorkspaceComposer {
  private noteIntent:{workspaceId:string;content:string;generation:number}|null=null;
  constructor(private readonly session:WorkspaceSession){}
  reset(){this.noteIntent=null;}
  prepareChief(prompt:string,host:ComposerContext){
    const {team,workspace,selected,thought,note}=this.session.getSnapshot(),bot=team?.configuration.bots.find(item=>botAddress(item)===selected);
    if(host.locked||host.connectionNavigationLocked||host.captureNavigationLocked||host.captureDraftLocked||!team?.revision||!team.llm.enabled||
      bot?.role!=='chief'||!bot.enabled||bot.retired||bot.blocked_capabilities?.includes('model_answer')||thought.trim()||
      note!==latestNotebookText(workspace)||!hasSavedBotContext(workspace,bot))return;
    this.session.setPhoneNoteTask(null);this.session.models.updateThought(prompt);this.session.setMobilePanel('Conversation');host.closeTools();host.focus();
  }
  requestScribe(host:ComposerContext){
    const {team,workspace,note,selected}=this.session.getSnapshot(),bot=team?.configuration.bots.find(item=>botAddress(item)===selected);
    const scribe=bot?.role==='scribe'?bot:team?.configuration.bots.find(item=>item.role==='scribe'&&!item.instance_id);
    if(!workspace||!scribe?.enabled||scribe.retired||!scribe.include_notebook||scribe.blocked_capabilities?.includes('model_answer')||!team?.llm.enabled||host.locked||!note.trim()||host.captureNavigationLocked||host.captureDraftLocked)return;
    if(note!==latestNotebookText(workspace)){
      this.noteIntent={workspaceId:workspace.id,content:note,generation:this.session.generation.current};
      void this.session.saves.append('scratchpad',note,undefined,host.save);return;
    }
    this.session.setSelected(botAddress(scribe));this.session.setPanel('Review');this.session.setMobilePanel('Review');
    void host.save.saveModel({type:'ask',model_contract:1,origin:'durable_admission_v1',body:{expected_revision:workspace.revision,team_revision:team.revision,
      idempotency_key:crypto.randomUUID(),role:botAddress(scribe),content:'Draft a clinical note from my saved notebook notes. Preserve the stated facts and uncertainty, do not invent missing information, and flag anything requiring my review.'}},'submit');
  }
  continueScribe(host:ComposerContext){
    const {workspace,busy,pending,conflict}=this.session.getSnapshot(),intent=this.noteIntent;
    if(!intent||busy)return;
    this.noteIntent=null;
    if(intent.generation===this.session.generation.current&&workspace?.id===intent.workspaceId&&latestNotebookText(workspace)===intent.content&&!pending&&!conflict&&!host.recoveryBlocked)this.requestScribe(host);
  }
  async askChief(content:string,host:ComposerContext){
    const {workspace,team,thought,note,selected}=this.session.getSnapshot(),bot=team?.configuration.bots.find(item=>botAddress(item)===selected);
    if(!workspace||!bot||host.locked||host.captureNavigationLocked||host.captureDraftLocked||note!==latestNotebookText(workspace)||thought.trim()||!team?.revision)return;
    await host.save.saveModel({type:'ask',model_contract:1,origin:'durable_admission_v1',body:{expected_revision:workspace.revision,team_revision:team.revision,
      idempotency_key:crypto.randomUUID(),role:botAddress(bot),content}},'submit');
  }
}

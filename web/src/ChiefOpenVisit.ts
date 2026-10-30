import type {Workspace} from './workspace-api';

/** What Chief can say about the visit that is already open. */
export class ChiefOpenVisit {
  static readonly missing = 'No visit details or saved notes were supplied. Open a visit, or save notebook notes or add a reference note, and ask again.';
  static readonly notesGap = 'Saved notes, intake, and preparation were not supplied. Save notebook notes or add a reference note on this visit, then ask again.';

  static countsAsContext(workspace:Workspace|null,role:string|undefined):boolean {
    return role==='chief'&&!!workspace?.appointment_id&&!!workspace.label.trim();
  }
  static savedDetails(workspace:Workspace):string[] {
    return workspace.entries.filter(entry=>entry.content.trim()&&(entry.kind==='synthetic_source'||entry.kind==='evidence'||entry.kind==='scratchpad')).map(entry=>entry.content.trim());
  }
  static identity(label:string):string {return `Open visit: ${label.trim()}.`;}
  static summary(workspace:Workspace|null):string {
    if(!ChiefOpenVisit.countsAsContext(workspace,'chief')||!workspace)return '';
    const detail=ChiefOpenVisit.savedDetails(workspace)[0];
    return detail?`${ChiefOpenVisit.identity(workspace.label)} ${detail.slice(0,180)}`:ChiefOpenVisit.identity(workspace.label);
  }
  static reply(workspace:Workspace):string {
    const summary=ChiefOpenVisit.summary(workspace);
    if(!summary)return ChiefOpenVisit.missing;
    const lines=['Saved encounter overview',`• Open visit: ${summary}`];
    if(!ChiefOpenVisit.savedDetails(workspace).length)lines.push(ChiefOpenVisit.notesGap);
    return lines.join('\n');
  }
}

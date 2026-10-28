/** Which Home checks block Start, and the one status line while they run. */
export class WorkspaceHomeStartup {
  /**
   * Start creates a private note. That needs the recovery journal (scope plus the
   * saved unconfirmed-create check). The team roster, visit list, and note list do not.
   */
  static startEnabled(input:{recoveryReady:boolean;busy:boolean;locked:boolean;pending:boolean;title:string}){
    return input.recoveryReady&&!input.busy&&!input.locked&&!input.pending&&input.title.trim().length>0;
  }

  static status(input:{recoveryReady:boolean;teamListed:boolean;visitsLoaded:boolean;notesLoaded:boolean;teamError:string}){
    if(input.teamError)return input.teamError;
    if(!input.recoveryReady){
      const background=!input.visitsLoaded||!input.notesLoaded?' Visits and notes are loading in the background.':'';
      return `Checking your team…${background}`;
    }
    const loading:[string,boolean][]=[['your team',!input.teamListed],['visits',!input.visitsLoaded],['notes',!input.notesLoaded]];
    const pending=loading.filter(([,waiting])=>waiting).map(([label])=>label);
    return pending.length?`Loading ${pending.join(' and ')}…`:'';
  }
}

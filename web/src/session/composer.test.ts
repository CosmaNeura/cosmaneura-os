// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {teamFixture,teamUuid} from '../team-setup-test-fixture';
import {notebookDraft} from '../draft-journal';
import type {Workspace} from '../workspace-api';
import type {ComposerContext} from './composer';
import {WorkspaceSession} from './workspace-session';

function fixture(){
  const session=new WorkspaceSession(),team=teamFixture(),workspace:Workspace={id:teamUuid(230),appointment_id:null,label:'Invented private note',revision:2,entries:[],work_candidates:[]};
  session.setWorkspace(workspace);session.setTeam(team);session.setSelected('chief');
  const host:ComposerContext={locked:false,connectionNavigationLocked:false,captureNavigationLocked:false,captureDraftLocked:false,recoveryBlocked:false,focus:vi.fn(),closeTools:vi.fn(),save:{notebookDraft,failure:vi.fn(),saveModel:vi.fn(async()=>{}),teamSaved:vi.fn(),coreNoteLinked:vi.fn()}};
  return {session,host,workspace,team};
}
describe('shared composer intent',()=>{
  it('does not ask Scribe until the exact jottings are confirmed saved',()=>{
    const f=fixture();f.session.setNote('Invented jottings');const append=vi.spyOn(f.session.saves,'append').mockResolvedValue(undefined);
    f.session.composer.requestScribe(f.host);expect(append).toHaveBeenCalledWith('scratchpad','Invented jottings',undefined,f.host.save);expect(f.host.save.saveModel).not.toHaveBeenCalled();
    f.session.setBusy(true);f.session.composer.continueScribe(f.host);expect(f.host.save.saveModel).not.toHaveBeenCalled();
    f.session.setWorkspace({...f.workspace,revision:3,entries:[{id:teamUuid(231),kind:'scratchpad',revision:3,content:'Invented jottings',origin:'human',created_at:'2026-10-23T12:00:00Z',source_label:null,ticket:null}]});f.session.setBusy(false);
    f.session.composer.continueScribe(f.host);expect(f.host.save.saveModel).toHaveBeenCalledOnce();expect(f.host.save.saveModel).toHaveBeenCalledWith(expect.objectContaining({body:expect.objectContaining({expected_revision:3,role:'scribe'})}),'submit');
  });
  it('does not resume a draft-note intent after changing the session',()=>{
    const f=fixture();f.session.setNote('Invented jottings');vi.spyOn(f.session.saves,'append').mockResolvedValue(undefined);
    f.session.composer.requestScribe(f.host);f.session.clear();f.session.composer.continueScribe(f.host);expect(f.host.save.saveModel).not.toHaveBeenCalled();
  });
  it('does not replace existing directions with a starter or enable a paused Chief',()=>{
    const f=fixture();f.session.setThought('Retained directions');f.team.configuration.bots.find(bot=>bot.role==='chief')!.enabled=false;f.session.setTeam(f.team);
    f.session.composer.prepareChief('A starter',f.host);expect(f.session.getSnapshot().thought).toBe('Retained directions');expect(f.host.focus).not.toHaveBeenCalled();expect(f.host.save.saveModel).not.toHaveBeenCalled();
  });
});

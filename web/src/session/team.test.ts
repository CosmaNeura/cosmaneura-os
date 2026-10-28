// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {notebookDraft} from '../draft-journal';
import {teamFixture,rehearsalFixture} from '../team-setup-test-fixture';
import type {ProviderTeam} from '../workspace-api';
import {WorkspaceSession} from './workspace-session';
import type {SaveContext} from './saves';

const identity={boxId:'invented-box',actorId:'invented-owner'};
function open(session:WorkspaceSession){const team=teamFixture();session.setIdentity(identity);session.setTeam(team);session.setTeamDraft(structuredClone(team.configuration));return team;}
const host=():SaveContext=>({notebookDraft,failure:vi.fn(),saveModel:vi.fn(async()=>{}),teamSaved:vi.fn(),coreNoteLinked:vi.fn()});

describe('shared team settings',()=>{
  it('does not overwrite a newer save with an older background read',async()=>{
    let finish!:(value:ProviderTeam)=>void;const session=new WorkspaceSession({teamRead:()=>new Promise(resolve=>{finish=resolve;})});const old=open(session);
    const reading=session.team.refresh({failure:vi.fn()});const latest={...old,revision:4};session.setTeam(latest);finish({...old,revision:2});await reading;
    expect(session.getSnapshot().team).toBe(latest);
  });
  it('preserves edits made while a background team read is in flight',async()=>{
    let finish!:(value:ProviderTeam)=>void;const session=new WorkspaceSession({teamRead:()=>new Promise(resolve=>{finish=resolve;})});const old=open(session);
    const reading=session.team.refresh({failure:vi.fn()});const draft={...old.configuration,practice_context:'Invented unsaved setting'};session.setTeamDraft(draft);
    finish({...old,revision:2});await reading;
    expect(session.getSnapshot()).toMatchObject({teamDraft:draft,conflict:true});
  });
  it('rejects a late read after account invalidation',async()=>{
    let finish!:(value:ProviderTeam)=>void;const session=new WorkspaceSession({teamRead:()=>new Promise(resolve=>{finish=resolve;})});const old=open(session);
    const reading=session.team.refresh({failure:vi.fn()});session.clear();finish(old);await expect(reading).rejects.toMatchObject({status:401});
    expect(session.getSnapshot().team).toBeNull();
  });
  it('saves only the reviewed exact configuration and revision; editing requires review again',async()=>{
    const session=new WorkspaceSession(),team=open(session),context=host(),save=vi.spyOn(session.saves,'save').mockResolvedValue(undefined);
    const draft=structuredClone(team.configuration);draft.bots[0].blocked_capabilities=['model_answer'];session.setTeamDraft(draft);
    await session.team.save(context);expect(save).not.toHaveBeenCalled();
    const review=(await rehearsalFixture(draft,team.revision)).setup_review;
    session.setSetupApproval({revision:team.revision,configurationKey:JSON.stringify(draft),review});await session.team.save(context);
    expect(save).toHaveBeenCalledOnce();expect(save.mock.calls[0][0]).toMatchObject({type:'team',body:{expected_revision:team.revision,configuration:draft,setup_review:review}});
    const changed=structuredClone(draft);changed.bots[0].name='Edited name';session.setTeamDraft(changed);await session.team.save(context);
    expect(save).toHaveBeenCalledOnce();expect(session.getSnapshot().error).toContain('review the current draft');
    session.setTeamDraft(draft);session.setTeam({...team,revision:team.revision+1});await session.team.save(context);expect(save).toHaveBeenCalledOnce();
  });
  it('retains the destination until the team exit is completed and clears it on access loss',()=>{
    const session=new WorkspaceSession(),team=open(session);session.setTeamDraft({...team.configuration,practice_context:'Edited practice'});const next=vi.fn();
    session.team.leave(true,next);expect(next).not.toHaveBeenCalled();expect(session.getSnapshot().confirmTeamExit).toBe(true);
    session.team.finishExit();expect(next).toHaveBeenCalledOnce();expect(session.getSnapshot().confirmTeamExit).toBe(false);
    session.team.leave(true,next);session.clear();session.team.finishExit();expect(next).toHaveBeenCalledOnce();
  });
});

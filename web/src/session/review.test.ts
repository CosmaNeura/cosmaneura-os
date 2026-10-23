// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {notebookDraft} from '../draft-journal';
import {teamFixture} from '../team-setup-test-fixture';
import type {AuthenticatedWorkspaceIdentity,DraftHandoff,Workspace} from '../workspace-api';
import type {ReviewContext} from './review';
import {WorkspaceSession} from './workspace-session';

const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const workspace:Workspace={id:'00000000-0000-4000-8000-000000000071',appointment_id:null,label:'Invented notebook',revision:4,entries:[],work_candidates:[]};
const handoff:DraftHandoff={id:'invented-handoff',origin_entry_id:'invented-origin',recipient_role:'follow_up',recipient_name:'Follow-up',brief:'Invented draft',context_revision:3,status:'completed',attempt_id:'invented-attempt',attempt_count:1,result_entry_id:'invented-result',result_sha256:'a'.repeat(64),error_code:null,attempts:[]};
function fixture(){
  const session=new WorkspaceSession();session.setIdentity(authenticated);session.setWorkspace(workspace);session.setTeam(teamFixture());session.setSelected('chief');
  const context:ReviewContext={authenticated,previousIdentity:{current:authenticated},actionLocked:false,viewNavigationLocked:false,captureNavigationLocked:false,captureDraftLocked:false,recoveryBlocked:false,phoneChatToolsOpen:false,setPhoneChatToolsOpen:vi.fn(),setClinicalTeamExpanded:vi.fn(),focusQuestion:vi.fn(),returnFocus:{current:null}};
  return {session,context};
}

describe('shared review navigation',()=>{
  it('opens the complete review for a hashed result and preserves the attributed recipient',()=>{
    const {session,context}=fixture();session.review.open(handoff,context);
    expect(session.getSnapshot()).toMatchObject({reviewHandoffId:handoff.id,selected:'follow_up',selectedResult:null,mobilePanel:'Conversation'});
    session.review.open({...handoff,result_sha256:null},context);
    expect(session.getSnapshot()).toMatchObject({reviewHandoffId:null,selectedResult:'invented-result'});
  });
  it('retains the current review while its decision is unconfirmed',()=>{
    const {session,context}=fixture();session.setReviewHandoffId(handoff.id);session.setHandoffReviewPending(true);
    session.review.close(context);session.review.open({...handoff,id:'another-invented-handoff'},context);
    expect(session.getSnapshot().reviewHandoffId).toBe(handoff.id);
  });
  it('prepares editable fresh-work text without sending or replacing an existing draft',()=>{
    const {session,context}=fixture();session.setThought('Existing invented directions');const save=vi.spyOn(session.saves,'save');
    session.review.prepareFresh('Keep the requested correction',context);
    expect(session.getSnapshot().thought).toBe('Existing invented directions\n\nPrepare fresh assignments using the current saved encounter sources.\nPlease preserve these requested changes: Keep the requested correction');
    expect(save).not.toHaveBeenCalled();expect(context.focusQuestion).toHaveBeenCalledOnce();
  });
  it('keeps an owner-disabled Chief disabled when fresh assignments are requested',()=>{
    const {session,context}=fixture(),team=teamFixture();team.configuration.bots.find(bot=>bot.role==='chief')!.enabled=false;session.setTeam(team);session.setThought('Retained invented text');
    session.review.prepareFresh('Correction',context);expect(session.getSnapshot().thought).toBe('Retained invented text');expect(session.getSnapshot().team?.configuration.bots.find(bot=>bot.role==='chief')?.enabled).toBe(false);expect(context.focusQuestion).not.toHaveBeenCalled();
  });
  it('binds a retry to the current workspace revision and prior attempt',()=>{
    const {session}=fixture(),saveModel=vi.fn(async()=>{});
    session.review.retry(handoff,{authenticated,notebookDraft,failure:vi.fn(),saveModel,teamSaved:vi.fn(),coreNoteLinked:vi.fn()});
    expect(saveModel).toHaveBeenCalledWith({type:'retry',model_contract:1,origin:'durable_admission_v1',handoffId:handoff.id,body:{expected_revision:4,previous_attempt_id:handoff.attempt_id,idempotency_key:expect.any(String)}},'submit');
  });
});

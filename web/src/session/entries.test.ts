// @vitest-environment node
import {describe,expect,it} from 'vitest';
import {teamFixture,teamUuid} from '../team-setup-test-fixture';
import type {DraftHandoff,Workspace,WorkspaceEntry} from '../workspace-api';
import {projectConversation,savedDraftReviewLabel} from './entries';

const team=teamFixture(),chief=team.members.find(bot=>bot.role==='chief')!;
const turn:WorkspaceEntry={id:teamUuid(250),revision:2,kind:'conversation',content:'Invented question',source_label:null,origin:'human',ticket:null,created_at:'2026-10-23T12:00:00Z',reply:{agent_name:'Chief',agent_id:chief.agent_id!,role:'chief',backend:'fake',content:'Invented response',context_revision:1,citations:[]}};
const result:WorkspaceEntry={...turn,id:teamUuid(251),kind:'handoff_result',content:'Internal invented brief',reply:{...turn.reply!,agent_id:team.members.find(bot=>bot.role==='follow_up')!.agent_id!,agent_name:'Follow-up',role:'follow_up',content:'Invented draft'}};
const handoff:DraftHandoff={id:teamUuid(252),origin_entry_id:turn.id,recipient_role:'follow_up',recipient_name:'Follow-up',recipient_agent_id:result.reply!.agent_id,brief:'Internal invented brief',context_revision:2,status:'completed',attempt_id:teamUuid(253),attempt_count:1,result_entry_id:result.id,result_sha256:'a'.repeat(64),error_code:null,attempts:[]};
const workspace:Workspace={id:teamUuid(254),appointment_id:null,label:'Invented notes',revision:3,entries:[turn,result],handoffs:[handoff],work_candidates:[]};
describe('shared conversation projection',()=>{
  it('gives Chief an attributed review card without adding the internal bot transcript',()=>{
    const projection=projectConversation(workspace,team,'chief');
    expect(projection.turns).toEqual([turn]);expect(projection.entries).toHaveLength(2);
    expect(projection.entries[1]).toMatchObject({kind:'review',author:'Follow-up',status:'Unreviewed draft',actions:[{kind:'review_handoff',id:handoff.id,label:'Review draft'}]});
    expect(JSON.stringify(projection.entries)).not.toContain('Internal invented brief');
  });
  it('does not call an earlier attempt or a different hash accepted',()=>{
    const reviewed={...handoff,review_status:'current' as const,review:{id:teamUuid(255),attempt_id:handoff.attempt_id,result_entry_id:result.id,result_sha256:'b'.repeat(64),decision:'accepted' as const,feedback:'',created_at:turn.created_at}};
    expect(savedDraftReviewLabel({...workspace,handoffs:[reviewed]},result)).toBe('Unreviewed draft');
    reviewed.review.result_sha256='a'.repeat(64);expect(savedDraftReviewLabel({...workspace,handoffs:[reviewed]},result)).toBe('Draft accepted');
  });
  it('withholds a revoked source result and its review action',()=>{
    const projection=projectConversation({...workspace,entries:[turn,{...result,content:'',reply:null,google_source_state:'unavailable'}]},team,'chief');
    expect(projection.entries[1]).toMatchObject({kind:'review',status:'Source access needs checking',actions:[]});
  });
  it('keeps direct specialist history separate from Chief',()=>{
    const projection=projectConversation(workspace,team,'follow_up');expect(projection.turns).toEqual([result]);expect(projection.entries).toHaveLength(1);
  });
});

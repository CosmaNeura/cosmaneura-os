// @vitest-environment node
import {describe,expect,it} from 'vitest';
import {teamFixture,teamUuid} from '../team-setup-test-fixture';
import type {DraftHandoff,FollowUp,PrivateNote,Workspace,WorkspaceEntry} from '../workspace-api';
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
  it.each(['google_source_state','microsoft_source_state'] as const)('withholds a revoked %s result and its review action',field=>{
    const projection=projectConversation({...workspace,entries:[turn,{...result,content:'',reply:null,[field]:'unavailable'}]},team,'chief');
    expect(projection.entries[1]).toMatchObject({kind:'review',status:'Source access needs checking',actions:[]});
  });
  it('keeps direct specialist history separate from Chief',()=>{
    const projection=projectConversation(workspace,team,'follow_up');expect(projection.turns).toEqual([result]);expect(projection.entries).toHaveLength(1);
  });
});

describe('saved Outlook material cards',()=>{
  const email:WorkspaceEntry={id:teamUuid(290),revision:4,kind:'microsoft_message',content:'Private invented email body must stay out of the card.',source_label:'Outlook: Invented follow-up',microsoft_source_state:'current',origin:'authenticated_human',ticket:null,created_at:'2026-10-25T12:15:00Z'};
  it('places Outlook and EHR metadata at their saved revisions without adding replies or body text',()=>{
    const ehr:WorkspaceEntry={...email,id:teamUuid(291),revision:3,kind:'ehr_read_source',microsoft_source_state:undefined,ehr_source_state:'current',source_label:'Elation: reviewed appointment'},later={...turn,id:teamUuid(292),revision:5};
    const projection=projectConversation({...workspace,revision:5,handoffs:[],entries:[later,email,ehr,turn]},team,'chief');
    expect(projection.entries.map(row=>row.id)).toEqual([turn.id,`source:${ehr.id}`,`source:${email.id}`,later.id]);expect(projection.turns).toEqual([later,turn]);
    expect(projection.entries[2]).toEqual({kind:'material',sourceKind:'outlook',id:`source:${email.id}`,sourceId:email.id,label:email.source_label,state:'current',createdAt:email.created_at});expect(JSON.stringify(projection.entries)).not.toContain(email.content);
  });
  it('requires Microsoft custody on an actual reviewed email and stays in Chief',()=>{
    const entries:WorkspaceEntry[]=[{...email,microsoft_source_state:undefined},{...email,id:teamUuid(293),microsoft_source_state:undefined,ehr_source_state:'current'},{...email,id:teamUuid(294),kind:'evidence'}];
    expect(projectConversation({...workspace,handoffs:[],entries},team,'chief').entries).toEqual([]);expect(projectConversation({...workspace,handoffs:[],entries:[email]},team,'follow_up').entries).toEqual([]);
  });
  it('replaces revoked Outlook metadata even when an old subject and body remain in the input',()=>{
    const projection=projectConversation({...workspace,handoffs:[],entries:[{...email,microsoft_source_state:'unavailable'}]},team,'chief');
    expect(projection.entries).toEqual([{kind:'material',sourceKind:'outlook',id:`source:${email.id}`,sourceId:email.id,label:'Unavailable email source',state:'unavailable',createdAt:email.created_at}]);expect(projection.turns).toEqual([]);expect(JSON.stringify(projection)).not.toContain('Invented follow-up');expect(JSON.stringify(projection)).not.toContain(email.content);
  });
});

describe('saved calendar file material cards',()=>{
 const calendar:WorkspaceEntry={id:teamUuid(310),revision:3,kind:'calendar_import_source',content:'Private invented event and Atlas.md body must not enter the card.',source_label:'Imported calendar snapshot',calendar_import_source_state:'current',origin:'authenticated_human',ticket:null,created_at:'2026-10-25T12:10:00Z'};
 it('projects only calendar metadata at its saved revision without reading the source body or creating a reply',()=>{
  const source={...calendar};Object.defineProperty(source,'content',{get:()=>{throw new Error('Card projection must not read calendar body');}});
  const later={...turn,id:teamUuid(311),revision:5},projection=projectConversation({...workspace,handoffs:[],entries:[later,source,turn]},team,'chief');
  expect(projection.entries.map(row=>row.id)).toEqual([turn.id,`source:${source.id}`,later.id]);expect(projection.entries[1]).toEqual({kind:'material',sourceKind:'calendar-import',id:`source:${source.id}`,sourceId:source.id,label:'Imported calendar snapshot',createdAt:source.created_at,state:'current'});expect(projection.turns).toEqual([later,turn]);expect(JSON.stringify(projection)).not.toContain('Atlas.md');
 });
 it('does not infer calendar material from a matching note, another calendar kind, or absent/wrong/unknown custody',()=>{
  const variants:WorkspaceEntry[]=[{...calendar,kind:'evidence'},{...calendar,id:teamUuid(312),kind:'google_calendar',calendar_source_state:'current'},{...calendar,id:teamUuid(313),calendar_import_source_state:undefined},{...calendar,id:teamUuid(314),calendar_import_source_state:undefined,calendar_source_state:'current'},{...calendar,id:teamUuid(315),calendar_import_source_state:'unknown'} as unknown as WorkspaceEntry];
  expect(projectConversation({...workspace,handoffs:[],entries:variants},team,'chief').entries).toEqual([]);expect(projectConversation({...workspace,handoffs:[],entries:[calendar]},team,'follow_up').entries).toEqual([]);expect(projectConversation({...workspace,handoffs:[],entries:[]},team,'chief').entries).toEqual([]);
 });
 it('masks unavailable metadata even if stale source label and body remain',()=>{
  const projection=projectConversation({...workspace,handoffs:[],entries:[{...calendar,source_label:'Private stale appointment label',calendar_import_source_state:'unavailable'}]},team,'chief');expect(projection.entries).toEqual([{kind:'material',sourceKind:'calendar-import',id:`source:${calendar.id}`,sourceId:calendar.id,label:'Unavailable calendar file summary',createdAt:calendar.created_at,state:'unavailable'}]);expect(JSON.stringify(projection)).not.toContain('Private');expect(projection.turns).toEqual([]);
 });
 it('uses a neutral label when the current typed source has no label',()=>{
  const projection=projectConversation({...workspace,handoffs:[],entries:[{...calendar,source_label:null}]},team,'chief');expect(projection.entries[0]).toMatchObject({sourceKind:'calendar-import',label:'Imported calendar snapshot'});
 });
});

describe('saved conversation order',()=>{
  const later:WorkspaceEntry={...turn,id:teamUuid(260),revision:9,content:'Invented later question',created_at:'2026-10-23T13:00:00Z'};
  it('keeps old result, note and linked work cards before a newly delivered turn',()=>{
    const note:PrivateNote={id:teamUuid(261),version:1,workspace_revision:4,content:'Invented private note',content_hash:'b'.repeat(64),source_reply_id:result.id,source_revision:3,source_fingerprint:'c'.repeat(64),sources_changed:false,created_at:turn.created_at,review:null};
    const work:FollowUp={ticket_id:teamUuid(262),revision_id:teamUuid(263),payload_hash:'d'.repeat(64),state:'pending_approval',create_key:'invented-create',body:'Invented follow-up',due_date:'2026-10-24',expected_outcome:'Invented outcome',owner_id:teamUuid(264),note_version:1,source_changed:false,operation_status:null,receipts:[]};
    const link:WorkspaceEntry={...turn,id:teamUuid(265),revision:5,kind:'work_link',reply:null,ticket:{id:work.ticket_id,state:work.state,lane:'follow_up'}};
    const projection=projectConversation({...workspace,revision:9,entries:[turn,{...result,revision:3},link,later],note:{latest:note,history:[note]},follow_ups:[work]},team,'chief');
    expect(projection.entries.map(row=>row.id)).toEqual([turn.id,`handoff:${handoff.id}`,`note:${note.id}`,`work:${work.ticket_id}`,later.id]);
    expect(projection.entries.filter(row=>row.kind==='review').flatMap(row=>row.actions.map(action=>action.kind))).toEqual(['review_handoff','review_note','review_work']);
    expect(projection.turns).toEqual([turn,later]);
  });
  it('leaves pending work at its saved context, then places an actually later result after the later turn',()=>{
    const pending={...handoff,status:'running' as const,result_entry_id:null,result_sha256:null};
    const before=projectConversation({...workspace,revision:9,entries:[turn,later],handoffs:[pending]},team,'chief');
    expect(before.entries.map(row=>row.id)).toEqual([turn.id,`handoff:${handoff.id}`,later.id]);
    expect(before.entries[1]).toMatchObject({status:'Working',actions:[]});
    const after=projectConversation({...workspace,revision:10,entries:[turn,later,{...result,revision:10}]},team,'chief');
    expect(after.entries.map(row=>row.id)).toEqual([turn.id,later.id,`handoff:${handoff.id}`]);
    expect(after.entries[2]).toMatchObject({status:'Unreviewed draft',actions:[{kind:'review_handoff',id:handoff.id,label:'Review draft'}]});
  });
});

describe('saved EHR material cards',()=>{
  const source:WorkspaceEntry={id:teamUuid(280),revision:3,kind:'ehr_read_source',content:'Private invented chart text must not enter the card.',source_label:'Elation: reviewed problem list',ehr_source_state:'current',origin:'authenticated_human',ticket:null,created_at:'2026-10-25T12:00:00Z'};
  it('places metadata-only material at its saved revision without creating a turn',()=>{
    const later={...turn,id:teamUuid(281),revision:5},projection=projectConversation({...workspace,revision:5,handoffs:[],entries:[later,source,turn]},team,'chief');
    expect(projection.entries.map(row=>row.id)).toEqual([turn.id,`source:${source.id}`,later.id]);expect(projection.turns).toEqual([later,turn]);expect(projection.entries[1]).toEqual({kind:'material',sourceKind:'ehr',id:`source:${source.id}`,sourceId:source.id,label:source.source_label,state:'current',createdAt:source.created_at});expect(JSON.stringify(projection.entries)).not.toContain(source.content);
  });
  it('does not infer material from a label, another bot, missing custody or a removed source',()=>{
    const w={...workspace,handoffs:[],entries:[{...source,kind:'evidence' as const},{...source,id:teamUuid(282),ehr_source_state:undefined}]};expect(projectConversation(w,team,'chief').entries).toEqual([]);expect(projectConversation({...workspace,entries:[source],handoffs:[]},team,'follow_up').entries).toEqual([]);expect(projectConversation({...workspace,entries:[],handoffs:[]},team,'chief').entries).toEqual([]);
  });
  it('replaces unavailable material metadata without exposing the old label or content',()=>{
    const projection=projectConversation({...workspace,handoffs:[],entries:[{...source,ehr_source_state:'unavailable',source_label:'Private old label'}]},team,'chief');expect(projection.entries).toEqual([{kind:'material',sourceKind:'ehr',id:`source:${source.id}`,sourceId:source.id,label:'Unavailable EHR source',state:'unavailable',createdAt:source.created_at}]);expect(projection.turns).toEqual([]);
  });
});

describe('saved Research material cards',()=>{
 const packet:WorkspaceEntry={id:teamUuid(300),revision:3,kind:'evidence',content:'Private invented excerpt and query must not enter the card.',source_label:'Research · public source excerpts',origin:'authenticated_human',ticket:null,created_at:'2026-10-25T12:00:00Z',research_packet:{contract:'research.saved_packet_marker.v1',run_id:teamUuid(301),entry_id:teamUuid(300),entry_revision:3}};
 it('places proven packet metadata at the saved entry revision without reading body or using its label as a fallback',()=>{
  const later={...turn,id:teamUuid(302),revision:5},source={...packet};Object.defineProperty(source,'content',{get:()=>{throw new Error('Projection must not read packet content');}});Object.defineProperty(source,'source_label',{get:()=>{throw new Error('Projection must use the fixed proven-packet label');}});
  const projection=projectConversation({...workspace,revision:5,handoffs:[],entries:[later,source,turn]},team,'chief');expect(projection.entries.map(row=>row.id)).toEqual([turn.id,`source:${packet.id}`,later.id]);expect(projection.entries[1]).toEqual({kind:'material',sourceKind:'research',id:`source:${packet.id}`,sourceId:packet.id,label:'Research · public source excerpts',state:'current',createdAt:packet.created_at});expect(projection.turns).toEqual([later,turn]);
 });
 it('does not infer packet identity from matching evidence text/label, missing markers, or another bot',()=>{
  const ordinary={...packet,research_packet:undefined};expect(projectConversation({...workspace,handoffs:[],entries:[ordinary]},team,'chief').entries).toEqual([]);expect(projectConversation({...workspace,handoffs:[],entries:[packet]},team,'research').entries).toEqual([]);expect(projectConversation({...workspace,handoffs:[],entries:[packet]},team,'follow_up').entries).toEqual([]);
 });
 it.each(['unknown-contract','mismatched-entry','mismatched-revision','invalid-run','extra-key','wrong-kind'] as const)('does not expose a Research card with %s metadata',change=>{
  const source=structuredClone(packet);if(change==='wrong-kind')source.kind='scratchpad';else if(change==='unknown-contract')source.research_packet={...source.research_packet!,contract:'research.saved_packet_marker.v2'} as unknown as WorkspaceEntry['research_packet'];else if(change==='mismatched-entry')source.research_packet!.entry_id=teamUuid(399);else if(change==='mismatched-revision')source.research_packet!.entry_revision=2;else if(change==='invalid-run')source.research_packet!.run_id='not-a-run';else source.research_packet={...source.research_packet!,content:'Untrusted body fallback'} as unknown as WorkspaceEntry['research_packet'];
  expect(projectConversation({...workspace,handoffs:[],entries:[source]},team,'chief').entries).toEqual([]);
 });
});

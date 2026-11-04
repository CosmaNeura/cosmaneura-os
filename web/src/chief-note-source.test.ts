import {expect,it} from 'vitest';
import {canReviewChiefNote,supportsChiefNoteSource} from './chief-note-source';
import type {WorkspaceEntry} from './workspace-api';

const answer=():WorkspaceEntry=>({id:'00000000-0000-4000-8000-000000000001',revision:3,kind:'conversation',content:'Invented question',source_label:null,ticket:null,origin:'synthetic_fixture',created_at:'2026-11-04T00:00:00Z',
  reply:{role:'chief',agent_name:'Chief',backend:'azure_gpt41',content:'Invented draft',context_revision:2,citations:[]}});

it('requires server support rather than assuming a new client means a new note API',()=>{
 expect(supportsChiefNoteSource({})).toBe(false);
 expect(supportsChiefNoteSource({note:{latest:null,history:[]}})).toBe(false);
 expect(supportsChiefNoteSource({note:{latest:null,history:[],allowed_reply_roles:['scribe','chief']}})).toBe(true);
});
it('offers only a completed Chief conversation with available current bound context',()=>{
 const entry=answer();expect(canReviewChiefNote(entry,2)).toBe(true);
 expect(canReviewChiefNote(entry,3)).toBe(false);
 expect(canReviewChiefNote({...entry,kind:'handoff_result'},2)).toBe(false);
 expect(canReviewChiefNote({...entry,reply:{...entry.reply!,role:'scribe'}},2)).toBe(false);
 expect(canReviewChiefNote({...entry,reply:{...entry.reply!,backend:'azure_gpt41_unavailable'}},2)).toBe(false);
 expect(canReviewChiefNote({...entry,reply:{...entry.reply!,context_revision:entry.revision}},2)).toBe(false);
});

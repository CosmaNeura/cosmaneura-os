import type {Workspace,WorkspaceEntry} from './workspace-api';
import {clinicalTeamRequest, type SharedClinicalNote} from './clinical-team-contract';
import {modelCanonical} from './model-work-request';
import {vendorSha256} from './vendor-contract';
import {researchBotId,researchWorkspaceId,researchFixtureId as id} from './research-test-fixture';

export async function noteResearchWorkspace():Promise<Workspace> {
  const hash=(content:string)=>vendorSha256(new TextEncoder().encode(content));
  const note={id:id(501),version:1,workspace_revision:1,content:'Invented SOAP note for Synthetic Person. Review DrugA interactions.',
    content_hash:'',source_reply_id:null,source_revision:1,source_fingerprint:'b'.repeat(64),sources_changed:false,
    created_at:'2026-10-22T12:00:00Z',review:null};
  note.content_hash=await hash(modelCanonical({content:note.content}));
  const snapshot:SharedClinicalNote={contract:'clinical-note-team-source.v1',request:{expected_revision:1,idempotency_key:id(502),note_id:note.id,
    note_version:1,content_hash:note.content_hash,source_fingerprint:note.source_fingerprint,share_with_team:true},
    note:{id:note.id,version:1,content:note.content,content_hash:note.content_hash,source_fingerprint:note.source_fingerprint}};
  const shared:WorkspaceEntry={id:id(503),revision:2,kind:'conversation',content:modelCanonical(snapshot),source_label:'Human-shared saved note',
    origin:'human',ticket:null,reply:null,created_at:note.created_at};
  const chief:WorkspaceEntry={id:id(504),revision:3,kind:'conversation',content:clinicalTeamRequest({entry:shared,snapshot},'Private-only direction: compare missing evidence.'),
    source_label:null,origin:'human',ticket:null,created_at:note.created_at,
    reply:{agent_name:'Chief',role:'chief',backend:'synthetic',content:'Research assignment saved.',context_revision:2,citations:[]}};
  const content='Source-supported findings\nThe saved note asks about DrugA interactions. [Human-shared saved note]\n\n'+
    'Drug and treatment questions\n1. Confirm interaction evidence for Synthetic Person.\nGeneral public query: DrugA interaction evidence\n\n'+
    'Missing evidence / next checks\nCurrent drug evidence has not been retrieved. Provider review is required.';
  const result:WorkspaceEntry={id:id(505),revision:4,kind:'handoff_result',content:'Exact Research assignment',source_label:null,origin:'agent',ticket:null,created_at:note.created_at,
    reply:{agent_name:'Research',agent_id:researchBotId,role:'research',backend:'synthetic',content,context_revision:3,
      citations:[{entry_id:shared.id,revision:shared.revision,label:shared.source_label!,kind:'evidence'}]}};
  const sourceText=`Human-shared saved note · version 1\nSaved private note snapshot; not clinical sign-off or a current chart read.\n\n${note.content}`;
  return {id:researchWorkspaceId,appointment_id:'invented-visit',label:'Invented visit',revision:4,entries:[shared,chief,result],work_candidates:[],note:{latest:note,history:[note]},
    handoffs:[{id:id(506),origin_entry_id:chief.id,recipient_role:'research',recipient_name:'Research',recipient_agent_id:researchBotId,recipient_key:researchBotId,
      brief:'Assess this exact saved note',context_revision:3,status:'completed',attempt_id:id(507),attempt_count:1,result_entry_id:result.id,
      result_sha256:await hash(content),review_status:'not_reviewed',error_code:null,attempts:[],
      task_brief:{version:2,goal:'Assess the exact saved note',missing_facts:['Current drug evidence'],expected_output:'Provider treatment assessment',completion_criteria:['Saved draft'],
        independent:true,allowed_actions:['prepare_private_draft'],depends_on:{entry_id:chief.id,revision:chief.revision},
        source_versions:[{entry_id:shared.id,revision:shared.revision,label:'Human-shared saved note',kind:'evidence',sha256:await hash(sourceText)}]}}]};
}

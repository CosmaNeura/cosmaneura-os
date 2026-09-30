import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {EncounterWorkSummary} from './EncounterWorkSummary';
import {workspaceApi,type Workspace,type PracticeWorkItem,type WorkspaceIdentity} from './workspace-api';
vi.mock('./workspace-api',async original=>({...await original<typeof import('./workspace-api')>(),workspaceApi:{practiceWorkItem:vi.fn()}}));
const identity:WorkspaceIdentity={boxId:'invented',actorId:'owner'};
const workspace:Workspace={id:'invented-visit',appointment_id:'invented',label:'Invented patient',revision:1,entries:[],work_candidates:[],follow_ups:[]};
const linked:Workspace={...workspace,entries:[{id:'link',revision:1,kind:'work_link',content:'',origin:'human',source_label:null,created_at:'2026-09-30T00:00:00Z',ticket:{id:'ticket',lane:'synthetic_followup',state:'sent'}}]};
const item:PracticeWorkItem={ticket_id:'ticket',version:1,revision_id:'r',payload_hash:'a'.repeat(64),state:'sent',body:'Confirm invented contact preference',due_date:'2026-10-01',expected_outcome:'Preference documented',viewer_id:'owner',originator:{id:'owner',name:'Morgan Ellis',available:true},responsible:{id:'owner',name:'Morgan Ellis',available:true},pending_offer:{id:'offer',from:{id:'owner',name:'Morgan Ellis',available:true},to:{id:'next',name:'Casey Rowan',available:true}},handoffs:[],receipts:[]};
let host:HTMLDivElement,root:Root;const denied=vi.fn();
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.resetAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function mount(w=workspace,owner=identity){await act(async()=>root.render(<EncounterWorkSummary workspace={w} identity={owner} locked={false} onReview={()=>{}} onPracticeWork={()=>{}} onAccessLost={denied}/>));}
it('does not invent an assignment or fetch unrelated practice work',async()=>{
  await mount();expect(host.textContent).toContain('Unassigned in this notebook');expect(host.textContent).toContain('No human follow-up task is linked to this notebook');expect(workspaceApi.practiceWorkItem).not.toHaveBeenCalled();
});
it('shows the verified person and keeps an offered handoff distinct from accepted responsibility',async()=>{
  vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue(item);await mount(linked);
  expect(host.textContent).toContain('Responsible: Morgan Ellis');expect(host.textContent).toContain('Handoff offered to Casey Rowan; awaiting acceptance. Morgan Ellis remains responsible');
  expect(vi.mocked(workspaceApi.practiceWorkItem).mock.calls[0][1]).toBe('ticket');
});
it('uses unknown rather than unassigned when a linked task cannot be read',async()=>{
  vi.mocked(workspaceApi.practiceWorkItem).mockRejectedValue(new Error('private sentinel'));await mount(linked);
  expect(host.textContent).toContain('Owner and current status could not be checked');expect(host.textContent).not.toContain('Unassigned');expect(host.textContent).not.toContain('private sentinel');
});
it('aborts and hides a late owner response after switching account or encounter',async()=>{
  let finish!:(item:PracticeWorkItem)=>void;vi.mocked(workspaceApi.practiceWorkItem).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  await mount(linked);const signal=vi.mocked(workspaceApi.practiceWorkItem).mock.calls[0][2]!;
  await mount({...workspace,id:'other'},{boxId:'other',actorId:'other'});expect(signal.aborted).toBe(true);
  await act(async()=>finish(item));expect(host.textContent).not.toContain('Morgan Ellis');
});
it('rejects a response belonging to a different task',async()=>{
  vi.mocked(workspaceApi.practiceWorkItem).mockResolvedValue({...item,ticket_id:'other'});await mount(linked);
  expect(host.textContent).not.toContain('Morgan Ellis');expect(host.textContent).toContain('could not be checked');
});

it('does not turn missing assignment information into an unassigned claim',async()=>{await mount({...workspace,follow_ups:undefined});expect(host.textContent).toContain('Assignment information unavailable');expect(host.textContent).not.toContain('Unassigned');});

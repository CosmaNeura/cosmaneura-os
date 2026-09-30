import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {TeamWorkPanel} from './TeamWorkPanel';
import type {DraftHandoff,WorkspaceEntry} from './workspace-api';

let root:Root,host:HTMLDivElement;const review=vi.fn(),retry=vi.fn();
const task:DraftHandoff={id:'invented-task',origin_entry_id:'chief',recipient_name:'Research',recipient_role:'research',recipient_agent_id:'research-agent',
  brief:'Compare invented sources',context_revision:2,status:'completed',attempt_id:'attempt',attempt_count:1,result_entry_id:'result',error_code:null,attempts:[],
  task_brief:{version:1,goal:'Compare invented sources',missing_facts:['Cardiac history and eligibility unconfirmed.'],expected_output:'Evidence comparison for review',
    completion_criteria:['Separate demo discussion from clinical statements.'],independent:true,allowed_actions:['prepare_private_draft'],depends_on:{entry_id:'chief',revision:3},
    source_versions:[{entry_id:'source',revision:2,label:'Invented transcript',kind:'evidence',sha256:'a'.repeat(64)}]}};
const result:WorkspaceEntry={id:'result',revision:4,kind:'handoff_result',content:task.brief,source_label:null,origin:'agent_handoff',ticket:null,created_at:'2026-09-30T00:00:00Z',
  reply:{agent_name:'Research',agent_id:'research-agent',role:'research',backend:'azure_gpt41',content:'Unconfirmed facts remain open.',context_revision:2,citations:[]}};
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
it('shows owner, goal, dependency, unresolved facts and exactly one result action',async()=>{
  await act(async()=>root.render(<TeamWorkPanel handoffs={[task]} entries={[result]} locked={false} onReview={review} onRetry={retry}/>));
  expect(host.textContent).toContain('Research');expect(host.textContent).toContain(task.brief);expect(host.textContent).toContain('Chief’s assignment saved');
  expect(host.textContent).toContain('Cardiac history and eligibility unconfirmed');expect(host.textContent).toContain('Clinical care and external work are not marked complete');
  const buttons=host.querySelectorAll('button');expect(buttons).toHaveLength(1);expect(buttons[0].textContent).toBe('Review result');
  await act(async()=>buttons[0].click());expect(review).toHaveBeenCalledExactlyOnceWith(task);expect(retry).not.toHaveBeenCalled();
});
it('never opens a missing or wrong-owner result and never fabricates completion from a queued task',async()=>{
  await act(async()=>root.render(<TeamWorkPanel handoffs={[task]} entries={[{...result,reply:{...result.reply!,agent_id:'other-agent'}}]} locked={false} onReview={review} onRetry={retry}/>));
  expect(host.querySelector('button')?.disabled).toBe(true);expect(host.textContent).toContain('Loading saved result');
  await act(async()=>root.render(<TeamWorkPanel handoffs={[{...task,status:'queued',result_entry_id:null}]} entries={[]} locked={false} onReview={review} onRetry={retry}/>));
  expect(host.textContent).toContain('1 working or queued · 0 drafts saved');expect(host.querySelector('button')).toBeNull();expect(review).not.toHaveBeenCalled();
});
it('keeps a Unicode-bounded goal preview while preserving the exact long brief behind one disclosure',async()=>{
  const goal='🫀'.repeat(165)+' Keep every invented unknown-speaker detail, without claiming clinical eligibility.';
  const longTask={...task,task_brief:{...task.task_brief!,goal}};
  await act(async()=>root.render(<TeamWorkPanel handoffs={[longTask]} entries={[result]} locked={false} onReview={review} onRetry={retry}/>));
  const card=host.querySelector('article')!,preview=card.querySelector('.team-task-goal')!,details=card.querySelector<HTMLDetailsElement>('.team-task-details')!;
  expect([...preview.textContent!]).toHaveLength(160);expect(preview.textContent).toBe('🫀'.repeat(159)+'…');
  expect(details.open).toBe(false);expect(details.querySelector('.team-task-full-goal')?.textContent).toBe(goal);
  expect(details.querySelector('.team-task-output')?.textContent).toBe(task.task_brief!.expected_output);
  expect(details.textContent).toContain(task.task_brief!.missing_facts[0]);expect(details.textContent).toContain(task.task_brief!.completion_criteria[0]);
  expect(details.textContent).toContain(task.task_brief!.source_versions[0].sha256);expect(details.textContent).toContain('revision 3');
  expect(card.querySelectorAll('button')).toHaveLength(1);const button=card.querySelector('button')!;
  expect(button.previousElementSibling).toBe(preview);expect(details.contains(button)).toBe(false);
  await act(async()=>details.querySelector('summary')!.click());expect(details.open).toBe(true);
  await act(async()=>button.click());expect(review).toHaveBeenCalledExactlyOnceWith(longTask);
});
it('keeps the existing task order and exact recipient binding when the visible list changes',async()=>{
  const second={...task,id:'second-task',recipient_name:'Follow-up',recipient_role:'follow_up' as const,recipient_agent_id:'follow-up-agent',result_entry_id:'follow-up-result'};
  const secondResult={...result,id:second.result_entry_id,reply:{...result.reply!,agent_id:second.recipient_agent_id,agent_name:second.recipient_name,role:second.recipient_role}};
  const render=async(handoffs:DraftHandoff[])=>act(async()=>root.render(<TeamWorkPanel handoffs={handoffs} entries={[result,secondResult]} locked={false} onReview={review} onRetry={retry}/>));
  await render([task,second]);expect([...host.querySelectorAll('article header strong')].map(node=>node.textContent)).toEqual(['Follow-up','Research']);
  await act(async()=>host.querySelector<HTMLButtonElement>('button')!.click());expect(review).toHaveBeenLastCalledWith(second);
  await render([second,task]);expect([...host.querySelectorAll('article header strong')].map(node=>node.textContent)).toEqual(['Research','Follow-up']);
  await act(async()=>host.querySelector<HTMLButtonElement>('button')!.click());expect(review).toHaveBeenLastCalledWith(task);
});
it('keeps every queued or running assignment visible in recent order and folds only older terminal work',async()=>{
  const assignments:DraftHandoff[]=[['old-queued','queued'],['old-failed','failed'],['old-running','running'],['new-ready','completed'],['new-failed','failed'],['latest-ready','completed']].map(([id,status])=>({...task,id,recipient_name:id,status:status as DraftHandoff['status'],result_entry_id:status==='completed'?'result':null}));
  const render=async(handoffs:DraftHandoff[])=>act(async()=>root.render(<TeamWorkPanel handoffs={handoffs} entries={[result]} locked={false} onReview={review} onRetry={retry}/>));
  await render(assignments);
  const names=()=>[...host.querySelectorAll('.team-work-overview>.team-task-grid>article header strong')].map(node=>node.textContent);
  expect(names()).toEqual(['latest-ready','new-failed','new-ready','old-running','old-queued']);
  const earlier=host.querySelector<HTMLDetailsElement>('.team-earlier-tasks')!;expect(earlier.open).toBe(false);expect(earlier.querySelectorAll('article')).toHaveLength(1);expect(earlier.querySelector('article header strong')?.textContent).toBe('old-failed');
  expect(earlier.textContent).not.toContain('Working on draft');expect(earlier.textContent).not.toContain('Queued');expect(host.querySelector('.team-work-overview>header')?.textContent).toContain('2 working or queued');
  await render(assignments.map(assignment=>assignment.id==='old-running'?{...assignment,status:'completed',result_entry_id:'result'}:assignment));
  expect(names()).toEqual(['latest-ready','new-failed','new-ready','old-queued']);expect([...host.querySelectorAll('.team-earlier-tasks article header strong')].map(node=>node.textContent)).toEqual(['old-running','old-failed']);
  expect(review).not.toHaveBeenCalled();expect(retry).not.toHaveBeenCalled();
});

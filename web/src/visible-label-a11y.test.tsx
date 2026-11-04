import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {HandoffCard} from './HandoffCard';
import {RoutineTimeInput} from './RoutineTimeInput';
import {VisitCatalog} from './VisitCatalog';
import type {AuthenticatedWorkspaceIdentity,DraftHandoff} from './workspace-api';

/** Visible text of a control, ignoring aria-hidden decoration. */
function visibleLabel(control: HTMLElement){
  const clone=control.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[aria-hidden="true"]').forEach(node=>node.remove());
  return (clone.textContent??'').replace(/\s+/g,' ').trim();
}

/** WCAG 2.5.3: accessible name must contain the visible label as a contiguous string. */
function assertLabelInName(control: HTMLElement){
  const visible=visibleLabel(control);
  if(!visible)return;
  const name=(control.getAttribute('aria-label')??visible).replace(/\s+/g,' ').trim();
  expect(name.toLocaleLowerCase(),`accessible name for “${visible}”`).toContain(visible.toLocaleLowerCase());
}

const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn()};

describe('visible label in accessible name (WCAG 2.5.3)',()=>{
  let root:Root,container:HTMLDivElement;
  beforeEach(()=>{
    Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});
    container=document.createElement('div');document.body.append(container);root=createRoot(container);
  });
  afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();});

  it('keeps Visit Catalog record actions labeled with the visible Record visit text',async()=>{
    await act(async()=>root.render(<VisitCatalog identity={identity} visits={[{appointment_id:uuid(101),label:'Invented morning visit',start_at:'2026-11-04T14:00:00Z',source:'synthetic',workspace_id:null}]} locked={false} recordingActive={false} onOpen={vi.fn()} onRecord={vi.fn()} onConnections={vi.fn()} onPrivateNote={vi.fn()}/>));
    const record=[...container.querySelectorAll<HTMLButtonElement>('button')].find(button=>visibleLabel(button)==='Record visit');
    expect(record).toBeTruthy();
    expect(record!.getAttribute('aria-label')).toBe('Record visit · Invented morning visit');
    assertLabelInName(record!);
  });

  it('keeps handoff review buttons named with their visible review copy',async()=>{
    const completed:DraftHandoff={
      id:uuid(201),origin_entry_id:uuid(202),recipient_role:'follow_up',recipient_name:'Follow-up',brief:'Invented private draft assignment',
      context_revision:1,status:'completed',attempt_id:uuid(203),attempt_count:1,result_entry_id:uuid(204),error_code:null,attempts:[],
    };
    await act(async()=>root.render(<HandoffCard handoff={completed} locked={false} resultAvailable onRetry={vi.fn()} onShow={vi.fn()}/>));
    const review=[...container.querySelectorAll<HTMLButtonElement>('button')].find(item=>visibleLabel(item)==='Review result');
    expect(review).toBeTruthy();
    expect(review!.getAttribute('aria-label')).toBe('Review result · Follow-up');
    assertLabelInName(review!);

    const masked:DraftHandoff={
      ...completed,result_sha256:'a'.repeat(64),task_brief_unavailable:true,review_status:'stale',brief:'Selected source unavailable',
    };
    await act(async()=>root.render(<HandoffCard handoff={masked} locked={false} resultAvailable={false} maskedResultAvailable onRetry={vi.fn()} onShow={vi.fn()}/>));
    const check=[...container.querySelectorAll<HTMLButtonElement>('button')].find(item=>visibleLabel(item)==='Check saved review');
    expect(check).toBeTruthy();
    expect(check!.getAttribute('aria-label')).toBe('Check saved review · Follow-up');
    assertLabelInName(check!);
  });

  it('keeps routine time toggles named with Use time picker / Type time',async()=>{
    await act(async()=>root.render(<RoutineTimeInput label="Brief time" value="09:45" onChange={vi.fn()}/>));
    const toggle=container.querySelector('button')!;
    expect(visibleLabel(toggle)).toBe('Type time');
    expect(toggle.getAttribute('aria-label')).toBe('Type time · Brief time');
    assertLabelInName(toggle);
    await act(async()=>toggle.click());
    expect(visibleLabel(toggle)).toBe('Use time picker');
    expect(toggle.getAttribute('aria-label')).toBe('Use time picker · Brief time');
    assertLabelInName(toggle);
  });

  it('rejects a mismatched aria-label that omits the visible button text',()=>{
    const button=document.createElement('button');
    button.textContent='Record privately';
    button.setAttribute('aria-label','Start a private recording');
    expect(()=>assertLabelInName(button)).toThrow(/accessible name/);
  });
});

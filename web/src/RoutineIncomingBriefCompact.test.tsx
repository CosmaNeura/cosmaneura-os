import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {RoutineIncomingBrief} from './RoutineIncomingBrief';
import {parseWorkBrief} from './routine-api';
import {parseIncomingBrief,type IncomingBriefSection} from './routine-inbox-contract';
import accepted from './__fixtures__/routine-inbox/actual-chief-accepted.json';
import unavailable from './__fixtures__/routine-inbox/actual-chief-unavailable.json';

let host:HTMLDivElement,root:Root;
const open=vi.fn();
const current=()=>parseWorkBrief(accepted.owner,accepted.owner.id).incoming!;
const visible=(node:Element)=>!node.closest('details:not([open])')||!!node.closest('summary');
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function mount(section:IncomingBriefSection|undefined=current(),blocked=false){
  await act(async()=>root.render(<RoutineIncomingBrief section={section} onOpen={open} blocked={blocked}/>));
}

it('puts actual current work before the closed nine-counter breakdown',async()=>{
  await mount();const details=host.querySelector('details')!;
  expect(details.open).toBe(false);expect(details.querySelector('summary')?.textContent).toBe('Counts and coverage details');
  expect(host.querySelectorAll('dt')).toHaveLength(9);
  expect([...host.querySelectorAll('dt,dd')].filter(visible)).toHaveLength(0);
  const work=host.querySelector('li')!;
  expect(work.compareDocumentPosition(details)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(visible(work)).toBe(true);expect(work.textContent).toContain('Please review the appointment question.');
  expect(host.querySelector('[aria-label="Incoming work summary"]')?.textContent).toBe('1 active.');
});

it('keeps a short priority summary to three nonzero counts',async()=>{
  const section=parseIncomingBrief({coverage:'partial',reason:'source_unavailable',items:[],matching_items:9,
    counts:{pending_approval:1,open:5,overdue:2,awaiting_acceptance:1,responsible_unavailable:1,
      awaiting_review:1,verified_complete:1,source_unavailable:1,work_changed:1},withheld_sources:true},'2026-09-22',2);
  await mount(section);
  const summary=host.querySelector('[aria-label="Incoming work summary"]')!;
  expect(summary.textContent).toBe('2 overdue · 1 awaiting review · 1 awaiting approval.');
  expect(summary.textContent!.split(' · ')).toHaveLength(3);
  expect([...host.querySelectorAll('dd')].filter(visible)).toHaveLength(0);
});

it('reveals the full existing counts through native details without navigation or mutation',async()=>{
  const section=current(),original=JSON.stringify(section);await mount(section);
  const details=host.querySelector('details')!;
  await act(async()=>details.querySelector('summary')!.click());
  expect(details.open).toBe(true);expect([...host.querySelectorAll('dt')].filter(visible)).toHaveLength(9);
  expect(details.textContent).toContain('A dated administrative handoff report');
  expect(open).not.toHaveBeenCalled();expect(JSON.stringify(section)).toBe(original);
  await act(async()=>details.querySelector('summary')!.click());
  expect(details.open).toBe(false);expect(open).not.toHaveBeenCalled();
});

it('keeps actual partial coverage and permitted work status visible while collapsing explanation',async()=>{
  await mount(parseWorkBrief(unavailable.owner,unavailable.owner.id).incoming!);
  const coverage=[...host.querySelectorAll('p')].find(p=>p.textContent?.startsWith('Coverage:'))!;
  expect(coverage.textContent).toContain('partial');expect(visible(coverage)).toBe(true);
  expect(visible(host.querySelector('li')!)).toBe(true);
  const explanation=[...host.querySelectorAll('p')].find(p=>p.textContent?.startsWith('Unavailable context'))!;
  expect(visible(explanation)).toBe(false);expect(host.textContent).not.toContain('Please review the appointment question.');
});

it.each(['collection_limit','source_unavailable'] as const)('keeps %s coverage unknown and never creates zero counts',async reason=>{
  const section=parseIncomingBrief({coverage:'unavailable',reason,items:[],matching_items:0,counts:null,withheld_sources:true},'2026-09-22',2);
  await mount(section);
  const visibleCopy=[...host.querySelectorAll('p')].filter(visible).map(p=>p.textContent).join(' ');
  expect(visibleCopy).toContain('unavailable · work counts are unknown');
  if(reason==='collection_limit')expect(visibleCopy).toContain('catalog limit reached');
  expect(visibleCopy).not.toContain('No incoming handoffs');expect(visibleCopy).not.toContain('0');
  expect(host.querySelector('[aria-label="Incoming work summary"]')).toBeNull();expect(host.querySelector('dl')).toBeNull();
});

it('leaves the earlier-report coverage label concise and unchanged',async()=>{
  const section=parseIncomingBrief({coverage:'not_included',reason:'legacy_report',items:[],matching_items:0,counts:null,withheld_sources:false},'2026-09-22',1);
  await mount(section);expect(host.textContent).toBe('Incoming handoffsThis earlier brief did not include incoming handoffs.');
  expect(host.querySelector('details')).toBeNull();
});

it('preserves the exact target callback and existing disabled behavior',async()=>{
  const section=current();await mount(section,true);
  const button=host.querySelector('button')!;expect(button.disabled).toBe(true);
  await act(async()=>button.click());expect(open).not.toHaveBeenCalled();
  await mount(section,false);await act(async()=>host.querySelector('button')!.click());
  expect(open).toHaveBeenCalledExactlyOnceWith(section.items[0].ticket_id);
});

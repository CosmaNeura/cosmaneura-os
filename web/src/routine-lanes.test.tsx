import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {parseWorkBrief} from './routine-api';
import type {AccountRecoveryAccess} from './account-recovery';
import type {ProviderTeam} from './workspace-api';
import actual from './__fixtures__/routine-lanes/actual-routine-lanes.json';
import legacy from './__fixtures__/routine-lanes/actual-legacy-routine.json';
import withheld from './__fixtures__/routine-lanes/actual-withheld-routine.json';
import revoked from './__fixtures__/routine-lanes/actual-revoked-routine.json';
import withdrawnResult from './__fixtures__/routine-lanes/actual-withdrawn-result-routine.json';

it('parses exact signed owner/staff and legacy reports without promoting historical work',()=>{
  for(const report of [actual.report,actual.staff_report,legacy.report,withheld.report,withdrawnResult.report]){
    const parsed=parseWorkBrief(report,report.id);expect(parsed).toEqual(report);
    for(const item of parsed.items)if(['withdrawn','superseded'].includes(item.state)){
      expect(item.human_completion).toBe(false);expect(item.ready_for_review??false).toBe(false);
    }
  }
  expect(parseWorkBrief(actual.report,actual.report.id).counts).toMatchObject({open:4,verified_complete:2});
  expect(parseWorkBrief(actual.staff_report,actual.staff_report.id).counts).toMatchObject({open:2,verified_complete:0});
});

it.each(['unknown','lane_state','missing_kind','missing_ready','nonboolean_ready','approved_complete',
  'withdrawn_complete','superseded_complete','withdrawn_ready','superseded_ready','closed_ready','terminal_offer',
  'false_open_count','false_complete_count'])('rejects contradictory or open-ended report semantics: %s',fault=>{
  const value=structuredClone(actual.report) as any;
  const row=(state:string)=>value.items.find((item:any)=>item.state===state);
  const approved=row('approved');
  if(fault==='unknown')approved.state='delivered_to_patient';
  if(fault==='lane_state')approved.work_kind='follow_up';
  if(fault==='missing_kind')delete approved.work_kind;
  if(fault==='missing_ready')delete approved.ready_for_review;
  if(fault==='nonboolean_ready')approved.ready_for_review='true';
  if(fault==='approved_complete')approved.human_completion=true;
  if(fault==='withdrawn_complete')row('withdrawn').human_completion=true;
  if(fault==='superseded_complete')row('superseded').human_completion=true;
  if(fault==='withdrawn_ready')row('withdrawn').ready_for_review=true;
  if(fault==='superseded_ready')row('superseded').ready_for_review=true;
  if(fault==='closed_ready')row('closed').ready_for_review=true;
  if(fault==='terminal_offer')row('superseded').pending_offer=true;
  if(fault==='false_open_count')value.counts.open=6;
  if(fault==='false_complete_count')value.counts.verified_complete=3;
  expect(()=>parseWorkBrief(value,value.id)).toThrow();
});

it('keeps legacy approved history generic and rejects contradictory legacy completion',()=>{
  const value=structuredClone(legacy.report);
  expect(parseWorkBrief(value,value.id).items.every(item=>item.work_kind===undefined)).toBe(true);
  value.items.find(item=>item.state==='approved')!.human_completion=true;
  expect(()=>parseWorkBrief(value,value.id)).toThrow();
});

it('bounds partial-report counts by visible facts and the number of hidden rows',()=>{
  const value=structuredClone(actual.report);
  for(let n=1;n<=2;n++)value.items.push({...value.items.find(item=>item.state==='approved')!,
    ticket_id:`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`});
  value.matching_items=12;
  const open=value.items.filter(item=>item.state==='approved'||item.state==='sent');
  value.counts={open:open.length,overdue:open.filter(item=>item.due_date<value.local_date).length,
    awaiting_acceptance:open.filter(item=>item.pending_offer).length,
    responsible_unavailable:open.filter(item=>!item.responsible.available).length,verified_complete:2};
  expect(parseWorkBrief(value,value.id).matching_items).toBe(12);
  expect(()=>parseWorkBrief({...value,counts:{...value.counts,open:open.length-1}},value.id)).toThrow();
  expect(()=>parseWorkBrief({...value,counts:{...value.counts,open:open.length+3}},value.id)).toThrow();
});

let root:Root|undefined,host:HTMLDivElement|undefined,access:AccountRecoveryAccess|undefined;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();});
afterEach(async()=>{if(root)await act(async()=>root!.unmount());root=undefined;access?.journal.close();access=undefined;
  host?.remove();host=undefined;vi.unstubAllGlobals();vi.unstubAllEnvs();});

async function mount(report:unknown=actual.report){
  for(const flag of ['VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_ROUTINES_ENABLED'])vi.stubEnv(flag,'true');
  vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.resetModules();
  const [{WorkRoutines},{AccountRecoveryContext},{DraftJournal},{memoryDraftStorage}]=await Promise.all([
    import('./WorkRoutines'),import('./account-recovery'),import('./draft-journal'),import('./draft-test-fixture')]);
  const state={report,status:200};
  const summary=report as typeof actual.report;
  const configuration={...actual.routine,runs:[{id:summary.id,scheduled_at:summary.scheduled_at,completed_at:summary.completed_at,local_date:summary.local_date}]};
  const fetch=vi.fn(async(url:string,options:RequestInit)=>{
    expect(options.method).toBe('GET');expect(options.body).toBeUndefined();
    expect((options.headers as Headers).get('Authorization')).toBe('Bearer invented.routine.token');
    expect(options).toMatchObject({credentials:'omit',redirect:'error',cache:'no-store'});
    if(url==='http://127.0.0.1:8000/provider-team/routines/chief')return Response.json(configuration,{headers:{'Cache-Control':'no-store'}});
    expect(url).toBe('http://127.0.0.1:8000/provider-team/routines/chief/runs/'+summary.id);
    return Response.json(state.report,{status:state.status,headers:{'Cache-Control':'no-store'}});
  });
  vi.stubGlobal('fetch',fetch);
  access={journal:new DraftJournal(await memoryDraftStorage()({scope:'routine-lane-render'})),authorize:vi.fn().mockResolvedValue(undefined)};
  const team:ProviderTeam={revision:1,template_version:'invented',configuration:{practice_context:'Invented practice',bots:[
    {role:'chief',name:'Chief',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[],llm:{enabled:false,model:'none'}};
  const lost=vi.fn();host=document.createElement('div');document.body.append(host);root=createRoot(host);
  await act(async()=>root!.render(<AccountRecoveryContext.Provider value={access!}><WorkRoutines
    identity={{mode:'clerk_jwt',getToken:async()=>'invented.routine.token'}} team={team} onAccessLost={lost}/></AccountRecoveryContext.Provider>));
  return {state,fetch,lost};
}

it('renders the actual parsed report as dated active, ready, historical, withdrawn and checked observations',async()=>{
  const {fetch}=await mount();
  expect(host!.textContent).toContain('Work observed on '+actual.report.local_date);
  const rows=[...host!.querySelectorAll('.routine-report li')];expect(rows).toHaveLength(8);
  expect(host!.textContent).toContain('Preparation awaiting a result');
  expect(host!.textContent).toContain('Preparation ready for provider review');
  expect(host!.textContent).toContain('Delivery work awaiting a result');
  expect(host!.textContent).toContain('Delivery result awaiting review');
  expect(host!.textContent).toContain('Superseded revision · historical, not complete');
  expect(host!.textContent).toContain('Withdrawn · not complete');
  expect(rows.filter(row=>row.textContent?.includes('Result checked'))).toHaveLength(2);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(host!.textContent).not.toContain('Later private revision');
});

it('renders actual legacy history without inventing lane or readiness details',async()=>{
  await mount(legacy.report);
  expect(host!.querySelectorAll('.routine-report li')).toHaveLength(8);
  expect(host!.textContent).toContain('Approved work awaiting a result');
  expect(host!.textContent).not.toContain('Preparation ready for provider review');
  expect(host!.textContent).toContain('Superseded revision · historical, not complete');
});

it('keeps retained vendor result evidence withdrawn in the actual mounted report',async()=>{
  await mount(withdrawnResult.report);
  const row=[...host!.querySelectorAll('.routine-report li')].find(item=>item.textContent?.includes('Invented routine withdrawn with result'));
  expect(row).toBeTruthy();expect(row!.textContent).toContain('Withdrawn · not complete');
  expect(row!.textContent).not.toContain('Result checked');expect(row!.textContent).not.toContain('awaiting review');
});

it('renders only current-authority source projections and removes private text on signed access loss',async()=>{
  const {state,fetch,lost}=await mount(withheld.report);
  expect(host!.textContent).toContain('have been withheld');
  expect(host!.textContent).not.toContain('Invented routine prep_active');
  expect(host!.querySelectorAll('.routine-report li')).toHaveLength(withheld.report.items.length);
  state.report=revoked.body;state.status=revoked.status;
  const refresh=[...host!.querySelectorAll('button')].find(button=>button.textContent==='Refresh briefs')!;
  await act(async()=>refresh.click());
  expect(host!.querySelector('.routine-report')).toBeNull();expect(lost).toHaveBeenCalledOnce();
  expect(fetch).toHaveBeenCalledTimes(4);
});

import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {WorkRoutines} from './WorkRoutines';
import {routineApi,parseWorkBrief} from './routine-api';
import incomingAccepted from './__fixtures__/routine-inbox/actual-chief-accepted.json';
import incomingUnavailable from './__fixtures__/routine-inbox/actual-chief-unavailable.json';
import {brief,routine,routineId} from './routine-test-fixture';
import {WorkspaceApiError,type ProviderTeam} from './workspace-api';
import {AccountRecoveryContext,type AccountRecoveryAccess} from './account-recovery';
import {DraftJournal,type AccountEditorDraft} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {DraftStoreError} from './draft-store';
vi.mock('./routine-api',async original=>({...await original<typeof import('./routine-api')>(),routineApi:{read:vi.fn(),save:vi.fn(),run:vi.fn()}}));
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented.token.value'};
const team:ProviderTeam={revision:1,template_version:'invented',configuration:{practice_context:'Invented practice',bots:[
  {role:'chief',name:'Chief',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true},
  {role:'custom',name:'Coordinator',instance_id:routineId(9),skills:['work_status'],enabled:true,response_style:'brief',include_notebook:false,include_evidence:false}]},members:[],llm:{enabled:false,model:'none'}};
let host:HTMLDivElement,root:Root,access:AccountRecoveryAccess,storage:ReturnType<typeof memoryDraftStorage>,failWrite:boolean;
const lost=vi.fn();
async function makeAccess():Promise<AccountRecoveryAccess>{const store=await storage({scope:'routine-compact'});return {journal:new DraftJournal({...store,
  async write(...args){if(failWrite)throw new DraftStoreError('unavailable');return store.write(...args);}}),authorize:vi.fn().mockResolvedValue(undefined)};}
beforeEach(async()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);
  storage=memoryDraftStorage();failWrite=false;access=await makeAccess();
  vi.mocked(routineApi.read).mockImplementation(async(_,bot)=>routine(bot));vi.mocked(routineApi.run).mockResolvedValue(brief());
  vi.mocked(routineApi.save).mockImplementation(async(_,bot,body)=>({...routine(bot),revision:2,configuration:body.configuration}));});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();host.remove();});
async function mount(currentIdentity=identity,onOpenIncoming?:(ticketId:string)=>void){await act(async()=>root.render(<AccountRecoveryContext.Provider value={access}><WorkRoutines identity={currentIdentity} team={team} onAccessLost={lost} onOpenIncoming={onOpenIncoming}/></AccountRecoveryContext.Provider>));}
async function restart(){await act(async()=>root.unmount());access.journal.close();access=await makeAccess();root=createRoot(host);await mount();}
async function record(){return await access.journal.load('account-editor:work-routine') as AccountEditorDraft|null;}
function visible(el:Element):boolean{
  if(el.closest('[hidden]'))return false;
  for(let p=el.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS'&&!(p as HTMLDetailsElement).open&&!p.querySelector('summary')?.contains(el))return false;
  return true;
}
function button(name:string){const el=[...host.querySelectorAll('button')].find(b=>b.textContent===name);expect(el,name).toBeTruthy();return el!;}
async function click(name:string){const el=button(name);expect(visible(el),`${name} visible`).toBe(true);await act(async()=>el.click());}
function field(label:string){const el=[...host.querySelectorAll('label')].find(l=>l.textContent?.startsWith(label))?.querySelector('input,select');expect(el,label).toBeTruthy();return el as HTMLInputElement|HTMLSelectElement;}
async function edit(label:string,value:string){const el=field(label);expect(visible(el),`${label} visible`).toBe(true);expect(el.matches(':disabled')).toBe(false);
  await act(async()=>{Object.getOwnPropertyDescriptor(el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value')!.set!.call(el,value);el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));});}
function details(name:string){const el=[...host.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent===name);expect(el,name).toBeTruthy();return el!;}
async function toggleDetails(name:string){const el=details(name);expect(visible(el)).toBe(true);await act(async()=>el.querySelector('summary')!.click());}
const visibleScheduleFields=()=>[...host.querySelectorAll('.routine-form input')].filter(visible);
async function timeView(label:string){const el=field(label).closest('.routine-time')!.querySelector('button')!;
  expect(visible(el)).toBe(true);await act(async()=>el.click());}

it('changes time entry views without creating a draft, changing the schedule, or running work',async()=>{
  await mount();await click('Edit schedule');const runs=vi.mocked(routineApi.run).mock.calls.length;
  await timeView('Brief time');expect(field('Brief time').type).toBe('text');await timeView('Brief time');
  await toggleDetails('Repeat, quiet hours and limits');await timeView('Quiet hours start');await timeView('Quiet hours end');
  expect(await record()).toBeNull();expect(routineApi.save).not.toHaveBeenCalled();expect(routineApi.run).toHaveBeenCalledTimes(runs);
});

it('recovers incomplete typed brief and quiet times exactly after navigation and restart',async()=>{
  await mount();await click('Edit schedule');await timeView('Brief time');await edit('Brief time','09:');
  await toggleDetails('Repeat, quiet hours and limits');await timeView('Quiet hours start');await edit('Quiet hours start','18:');
  await timeView('Quiet hours end');await edit('Quiet hours end','7:');const saved=await record();
  expect(saved?.data).toMatchObject({configuration:{at:'09:',quiet_start:'18:',quiet_end:'7:'}});
  await click('Back to briefs');await click('Edit schedule');expect(field('Brief time').value).toBe('09:');
  await restart();await click('Restore work routine draft');expect(field('Brief time').type).toBe('text');expect(field('Brief time').value).toBe('09:');
  await toggleDetails('Repeat, quiet hours and limits');expect(field('Quiet hours start').type).toBe('text');expect(field('Quiet hours start').value).toBe('18:');
  expect(field('Quiet hours end').value).toBe('7:');expect(button('Save schedule').disabled).toBe(true);
  expect(await record()).toEqual(saved);expect(routineApi.save).not.toHaveBeenCalled();
});

it('saves corrected typed times with the existing exact request and retains it through lost-response recovery',async()=>{
  vi.mocked(routineApi.save).mockRejectedValueOnce(new WorkspaceApiError(503));await mount();await click('Edit schedule');
  await timeView('Brief time');await edit('Brief time','9:30');expect(button('Save schedule').disabled).toBe(true);
  await edit('Brief time','09:30');await click('Save schedule');const sent=vi.mocked(routineApi.save).mock.calls[0][2];
  expect(sent.configuration.at).toBe('09:30');expect(field('Brief time').matches(':disabled')).toBe(true);
  expect(field('Brief time').closest('.routine-time')!.querySelector('button')!.disabled).toBe(true);
  await restart();await click('Restore work routine draft');expect(field('Brief time').value).toBe('09:30');
  expect(routineApi.save).toHaveBeenCalledOnce();await click('Retry same schedule save');
  expect(vi.mocked(routineApi.save).mock.calls[1][2]).toEqual(sent);expect(await record()).toBeNull();
});

it('retains invalid typed text and blocks save when local journaling fails',async()=>{
  await mount();await click('Edit schedule');await timeView('Brief time');await edit('Brief time','09:30');const durable=await record();
  failWrite=true;await edit('Brief time','24:00');expect(field('Brief time').value).toBe('24:00');
  expect(button('Save schedule').disabled).toBe(true);expect(button('Back to briefs').disabled).toBe(true);
  expect(await record()).toEqual(durable);expect(routineApi.save).not.toHaveBeenCalled();
});

it('starts with the dated brief, saved status and next run but no visible schedule fields or history selector',async()=>{
  await mount();expect(host.textContent).toContain('Work observed on 2026-09-21');expect(host.textContent).toContain("Today's brief is saved");
  expect(host.textContent).toContain('Next scheduled:');expect(visibleScheduleFields()).toHaveLength(0);
  expect(visible(button('Edit schedule'))).toBe(true);expect(visible(field('Saved brief'))).toBe(false);
  expect(visible(button('Save schedule'))).toBe(false);expect(routineApi.save).not.toHaveBeenCalled();
});

it('keeps an unconfigured routine compact until explicitly opened',async()=>{
  vi.mocked(routineApi.read).mockResolvedValue({...routine(),revision:0,configuration:null,status:'not_configured',next_scheduled_at:null,runs:[]});
  await mount();expect(host.textContent).toContain('Not scheduled');expect(host.textContent).toContain('No saved brief yet.');expect(visibleScheduleFields()).toHaveLength(0);
  await click('Edit schedule');expect(visible(field('Time zone'))).toBe(true);expect((field('Prepare scheduled briefs') as HTMLInputElement).checked).toBe(false);
  expect(routineApi.save).not.toHaveBeenCalled();expect(routineApi.run).not.toHaveBeenCalled();
});

it('opens only essentials and exposes repeat, quiet hours and limits on demand',async()=>{
  await mount();await click('Edit schedule');expect(visible(field('Time zone'))).toBe(true);expect(visible(field('Brief time'))).toBe(true);
  expect(visible(field('Mon'))).toBe(false);expect(visible(field('Use quiet hours'))).toBe(false);expect(visible(field('Maximum briefs in seven days'))).toBe(false);
  await toggleDetails('Repeat, quiet hours and limits');expect(visible(field('Mon'))).toBe(true);expect(visible(field('Quiet hours start'))).toBe(true);
  expect(routineApi.save).not.toHaveBeenCalled();
});

it('returns to the dated brief and reopens the same mounted editor with every draft choice intact',async()=>{
  await mount();await click('Edit schedule');const timezone=field('Time zone');await edit('Time zone','America/');await edit('Brief time','');
  await toggleDetails('Repeat, quiet hours and limits');await act(async()=>(field('Sat') as HTMLInputElement).click());await edit('Maximum briefs in seven days','6');
  const saved=await record();expect(saved?.data).toMatchObject({configuration:{timezone:'America/',at:'',weekdays:[1,2,3,4,5,6],max_runs_per_seven_days:6}});
  await click('Back to briefs');expect(visibleScheduleFields()).toHaveLength(0);expect(visible(host.querySelector('.routine-report')!)).toBe(true);
  expect(host.textContent).toContain('Unfinished schedule retained');expect(await record()).toEqual(saved);
  await click('Edit schedule');expect(field('Time zone')).toBe(timezone);expect(field('Time zone').value).toBe('America/');expect(field('Brief time').value).toBe('');
  expect(details('Repeat, quiet hours and limits').open).toBe(true);expect(button('Save schedule').disabled).toBe(true);expect(routineApi.save).not.toHaveBeenCalled();
});

it('shows next run from saved settings rather than an unsaved pause',async()=>{
  await mount();await click('Edit schedule');await act(async()=>(field('Prepare scheduled briefs') as HTMLInputElement).click());await click('Back to briefs');
  expect(host.textContent).toContain('Next scheduled:');expect(host.textContent).toContain('Unfinished schedule retained');expect(routineApi.save).not.toHaveBeenCalled();
});

it('lets a dated history read occur from the overview without resetting a retained schedule',async()=>{
  await mount();await click('Edit schedule');await edit('Brief time','10:00');await click('Back to briefs');const before=await record();
  await toggleDetails('Earlier briefs');await edit('Saved brief',routineId(1));expect(routineApi.run).toHaveBeenCalledTimes(3);expect(await record()).toEqual(before);
  await click('Edit schedule');expect(field('Brief time').value).toBe('10:00');expect(routineApi.save).not.toHaveBeenCalled();
});

it('keeps an unconfirmed save visible, blocks return and retries only the same journaled request',async()=>{
  vi.mocked(routineApi.save).mockRejectedValueOnce(new WorkspaceApiError(503));await mount();await click('Edit schedule');await edit('Brief time','09:00');await click('Save schedule');
  const first=vi.mocked(routineApi.save).mock.calls[0],before=await record();expect(before?.data).toMatchObject({pending:first[2]});
  expect(host.textContent).toContain('This schedule save is unconfirmed');expect(visible(button('Retry same schedule save'))).toBe(true);
  expect(button('Back to briefs').disabled).toBe(true);await click('Back to briefs');expect(visible(field('Brief time'))).toBe(true);expect(await record()).toEqual(before);
  await click('Retry same schedule save');expect(vi.mocked(routineApi.save).mock.calls[1]).toEqual(first);expect(await record()).toBeNull();
  await click('Back to briefs');expect(host.textContent).toContain('Schedule saved.');expect(visibleScheduleFields()).toHaveLength(0);
});

it('keeps navigation blocked while dispatch is in flight without replacing the exact request',async()=>{
  let release!:(value:ReturnType<typeof routine>)=>void;vi.mocked(routineApi.save).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
  await mount();await click('Edit schedule');await edit('Brief time','09:00');await click('Save schedule');
  const original=vi.mocked(routineApi.save).mock.calls[0][2];expect(button('Back to briefs').disabled).toBe(true);expect(visible(field('Brief time'))).toBe(true);
  await click('Back to briefs');expect(routineApi.save).toHaveBeenCalledOnce();expect((await record())?.data).toMatchObject({pending:original});
  await act(async()=>release({...routine(),revision:2,configuration:original.configuration}));expect(button('Back to briefs').disabled).toBe(false);
});

it('retains rejected-save controls and input until fresh comparison and explicit setting aside',async()=>{
  vi.mocked(routineApi.save).mockRejectedValueOnce(new WorkspaceApiError(409));await mount();await click('Edit schedule');await edit('Brief time','09:00');await click('Save schedule');
  expect(button('Back to briefs').disabled).toBe(true);expect(visible(button('Check current schedule'))).toBe(true);expect(field('Brief time').value).toBe('09:00');
  const exact=await record();await click('Check current schedule');expect(await record()).toEqual(exact);await click('Set aside rejected schedule request');
  expect((await record())?.pending).toBeNull();await click('Back to briefs');await click('Edit schedule');expect(field('Brief time').value).toBe('09:00');expect(routineApi.save).toHaveBeenCalledOnce();
});

it('cannot hide a volatile draft behind overview after local write failure',async()=>{
  await mount();await click('Edit schedule');await edit('Brief time','09:00');const durable=await record();failWrite=true;await edit('Brief time','10:00');
  expect(host.textContent).toContain('Local form storage is unavailable');expect(button('Back to briefs').disabled).toBe(true);expect(button('Save schedule').disabled).toBe(true);
  await click('Back to briefs');expect(visible(field('Brief time'))).toBe(true);expect(field('Brief time').value).toBe('10:00');expect(await record()).toEqual(durable);expect(routineApi.save).not.toHaveBeenCalled();
});

it('keeps an unsent pending request visible if journaling fails before dispatch',async()=>{
  await mount();await click('Edit schedule');await edit('Brief time','09:00');failWrite=true;await click('Save schedule');
  expect(host.textContent).toContain('The schedule was not sent.');expect(host.textContent).toContain('Local form storage is unavailable');expect(button('Back to briefs').disabled).toBe(true);
  expect(visible(field('Brief time'))).toBe(true);expect(routineApi.save).not.toHaveBeenCalled();
});

it('explicit restoration opens the retained incomplete custom-bot editor without saving or running it',async()=>{
  await mount();await edit('Coworker',routineId(9));await click('Edit schedule');await edit('Time zone','America/');await edit('Brief time','');const original=await record();await restart();
  expect(visibleScheduleFields()).toHaveLength(0);const runsBefore=vi.mocked(routineApi.run).mock.calls.length;await click('Restore work routine draft');
  expect(visible(field('Time zone'))).toBe(true);expect(field('Time zone').value).toBe('America/');expect(field('Brief time').value).toBe('');expect(field('Coworker').value).toBe(routineId(9));
  expect(button('Save schedule').disabled).toBe(true);expect(access.authorize).toHaveBeenCalledOnce();expect(await record()).toEqual(original);
  expect(routineApi.save).not.toHaveBeenCalled();expect(routineApi.run).toHaveBeenCalledTimes(runsBefore);
  await edit('Time zone','UTC');await edit('Brief time','09:00');expect(button('Save schedule').disabled).toBe(false);expect(routineApi.save).not.toHaveBeenCalled();
});

it('opens restored exact pending input and exposes only explicit retry after a restart',async()=>{
  vi.mocked(routineApi.save).mockRejectedValueOnce(new WorkspaceApiError(503));await mount();await click('Edit schedule');await edit('Brief time','09:00');await click('Save schedule');
  const original=vi.mocked(routineApi.save).mock.calls[0][2];await restart();await click('Restore work routine draft');expect(visible(field('Brief time'))).toBe(true);expect(field('Brief time').value).toBe('09:00');
  expect(button('Back to briefs').disabled).toBe(true);expect(visible(button('Retry same schedule save'))).toBe(true);expect(routineApi.save).toHaveBeenCalledOnce();
  await click('Retry same schedule save');expect(vi.mocked(routineApi.save).mock.calls[1][2]).toEqual(original);expect(await record()).toBeNull();
});

it('keeps stale restored settings visible until the current saved revision is explicitly chosen',async()=>{
  await mount();await click('Edit schedule');await edit('Brief time','09:00');vi.mocked(routineApi.read).mockResolvedValue({...routine(),revision:2});await restart();await click('Restore work routine draft');
  expect(visible(field('Brief time'))).toBe(true);expect(host.textContent).toContain('earlier saved version');expect(button('Save schedule').disabled).toBe(true);
  await click('Back to briefs');expect(host.textContent).toContain('earlier saved version');await click('Edit schedule');await click('Use these settings with the current schedule');
  expect(field('Brief time').value).toBe('09:00');expect(routineApi.save).not.toHaveBeenCalled();
});

it('removes both mounted form and private report when refreshed access is revoked',async()=>{
  await mount();await click('Edit schedule');await edit('Time zone','Private draft');await click('Back to briefs');vi.mocked(routineApi.read).mockRejectedValueOnce(new WorkspaceApiError(403));await click('Reload saved schedule');
  expect(host.querySelector('.routine-form')).toBeNull();expect(host.querySelector('.routine-report')).toBeNull();expect(host.innerHTML).not.toContain('Private draft');expect(lost).toHaveBeenCalledOnce();
});


it('freshly checks the retained report on return and removes cached private sources after authority loss',async()=>{
  await mount();await click('Edit schedule');await edit('Brief time','09:00');
  vi.mocked(routineApi.run).mockRejectedValueOnce(new WorkspaceApiError(403));await click('Back to briefs');
  expect(routineApi.run).toHaveBeenCalledTimes(2);expect(host.querySelector('.routine-report')).toBeNull();expect(host.querySelector('.routine-form')).toBeNull();
  expect(host.textContent).not.toContain('Confirm invented appointment');expect(lost).toHaveBeenCalledOnce();expect(routineApi.save).not.toHaveBeenCalled();
});

it('withholds a prior brief while the explicit return read is uncertain and retains the schedule draft',async()=>{
  await mount();await click('Edit schedule');await edit('Brief time','09:00');const before=await record();
  vi.mocked(routineApi.run).mockRejectedValueOnce(new WorkspaceApiError(503));await click('Back to briefs');
  expect(host.querySelector('.routine-report')).toBeNull();expect(host.textContent).toContain('could not be confirmed');expect(await record()).toEqual(before);
  await click('Edit schedule');expect(field('Brief time').value).toBe('09:00');expect(routineApi.save).not.toHaveBeenCalled();
});


it('moves keyboard focus to visible headings when opening and returning during a fresh read',async()=>{
  await mount();await click('Edit schedule');expect(document.activeElement).toBe(host.querySelector('.routine-editor h3'));
  let release!:(value:ReturnType<typeof brief>)=>void;vi.mocked(routineApi.run).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
  await click('Back to briefs');expect(button('Edit schedule').disabled).toBe(true);expect(document.activeElement).toBe(host.querySelector('h2'));
  expect(visible(document.activeElement!)).toBe(true);await act(async()=>release(brief()));
});


it('opens only the current incoming target from a signed dated observation and keeps schedule drafts safe',async()=>{
  const report=parseWorkBrief(incomingAccepted.owner,incomingAccepted.owner.id),open=vi.fn();
  vi.mocked(routineApi.run).mockResolvedValue(report);await mount(identity,open);
  expect(host.textContent).toContain('Incoming handoffs');expect(host.textContent).toContain('Active internal follow-up');
  expect(host.textContent).not.toContain("next week's appointment");
  await click('Open current incoming follow-up');expect(open).toHaveBeenCalledExactlyOnceWith(report.incoming!.items[0].ticket_id);
  expect(routineApi.save).not.toHaveBeenCalled();expect(await record()).toBeNull();
  await click('Edit schedule');await edit('Brief time','10:00');await click('Back to briefs');const retained=await record();
  expect(button('Open current incoming follow-up').disabled).toBe(true);await click('Open current incoming follow-up');
  expect(open).toHaveBeenCalledOnce();expect(await record()).toEqual(retained);expect(routineApi.save).not.toHaveBeenCalled();
});

it('renders actual source-unavailable responsibility without restoring old context or completion',async()=>{
  vi.mocked(routineApi.run).mockResolvedValue(parseWorkBrief(incomingUnavailable.owner,incomingUnavailable.owner.id));await mount();
  const section=host.querySelector('[aria-label="Incoming work coverage"]')!;
  expect(section.textContent).toContain('partial');expect(section.textContent).toContain('Source unavailable');
  expect(section.textContent).toContain('Invented recipient');expect(section.textContent).not.toContain('Please review the appointment question');
  const verified=[...section.querySelectorAll('dt')].find(x=>x.textContent==='Locally verified')!;
  expect(verified.nextElementSibling?.textContent).toBe('0');expect(routineApi.save).not.toHaveBeenCalled();
});

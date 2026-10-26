import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {ConversationEntries} from './ConversationEntries';
import type {ConversationProjection} from './session/entries';
import type {WorkspaceEntry} from './workspace-api';

let root:Root,host:HTMLDivElement;
const source=vi.fn(),check=vi.fn(),action=vi.fn();
function entry(id:string,time:string):WorkspaceEntry{return {id,revision:2,kind:'conversation',content:'Invented question',source_label:null,origin:'human',ticket:null,created_at:time,
  reply:{agent_name:'Chief',role:'chief',backend:'azure_gpt41',content:'Invented answer',context_revision:1,citations:[{entry_id:'source-a',revision:1,label:'Invented notes',kind:'scratchpad'}]}};}
const turns=[entry('one','2026-10-23T12:00:00Z'),entry('two','2026-10-23T12:05:00Z'),entry('three','2026-10-23T12:30:00Z')];
const projection:ConversationProjection={workspaceId:'invented',botAddress:'chief',turns,entries:turns.map(entry=>({kind:'turn',id:entry.id,entry,reviewLabel:'Unreviewed draft',actions:[]}))};
async function render(presentation:'messages'|'workspace'='messages',value=projection){await act(async()=>root.render(<ConversationEntries presentation={presentation} projection={value} latestSourceRevision={2} busy={false} recoveryBlocked={false} locked={false} onWork={()=>{}} onSource={source} onCheck={check} onAction={action}/>));}
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);vi.clearAllMocks();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
it('keeps the same entries with quiet delivery state and 15-minute separators',async()=>{
  await render();expect([...host.querySelectorAll('[data-entry-id]')].map(node=>node.getAttribute('data-entry-id'))).toEqual(['one','two','three']);
  expect(host.querySelectorAll('.messages-time-separator')).toHaveLength(2);expect(host.querySelectorAll('.messages-delivery')).toHaveLength(1);
  expect(host.querySelector('#turn-three .messages-delivery')?.textContent).toBe('Delivered');
  expect(host.textContent).not.toContain('GPT-4.1');expect(host.querySelector('details')).toBeNull();
});
it('opens source provenance on demand, preserves stale-source warning and calls the same source action',async()=>{
  await render();const details=host.querySelector<HTMLButtonElement>('.messages-source-details')!;
  details.focus();await act(async()=>details.click());expect(host.querySelector('[role=dialog]')?.textContent).toContain('Newer sources are available');
  const citation=[...host.querySelectorAll<HTMLButtonElement>('[role=dialog] button')].find(node=>node.textContent==='Invented notes')!;
  await act(async()=>citation.click());expect(source).toHaveBeenCalledExactlyOnceWith('source-a');expect(host.querySelector('[role=dialog]')).toBeNull();expect(document.activeElement).toBe(details);
});
it('closes provenance when the conversation changes and retains Workspace markup',async()=>{
  await render();await act(async()=>host.querySelector<HTMLButtonElement>('.messages-source-details')!.click());
  await render('messages',{...projection,botAddress:'follow_up'});expect(host.querySelector('[role=dialog]')).toBeNull();
  await render('workspace');expect(host.textContent).not.toContain('GPT-4.1');expect(host.querySelectorAll('details')).toHaveLength(3);expect(host.querySelector('.messages-delivery')).toBeNull();
});
it('does not refocus a retained Message details button after its local conversation episode changes',async()=>{
 await render();const opener=host.querySelector<HTMLButtonElement>('.messages-source-details')!;await act(async()=>opener.click());const focus=vi.spyOn(opener,'focus');await render('messages',{...projection,botAddress:'follow_up'});expect(host.querySelector('.messages-source-details')).toBe(opener);expect(focus).not.toHaveBeenCalled();await render();expect(focus).not.toHaveBeenCalled();
});

it.each(['messages','workspace'] as const)('shows two saved-source cards in %s with distinct time associations and exact source actions',async presentation=>{
 const material=(id:string,createdAt:string)=>({kind:'material' as const,sourceKind:'ehr' as const,id:`source:${id}`,sourceId:id,label:'Elation: reviewed problem list',createdAt,state:'current' as const});
 await render(presentation,{...projection,entries:[projection.entries[0],material('source-one','2026-10-25T12:00:00Z'),material('source-two','2026-10-25T12:15:00Z'),...projection.entries.slice(1)]});
 const cards=[...host.querySelectorAll<HTMLElement>('.conversation-material-card')];expect(cards).toHaveLength(2);expect(cards.every(card=>card.textContent?.includes('Saved EHR source'))).toBe(true);expect(cards[0].querySelector('time')?.dateTime).toBe('2026-10-25T12:00:00Z');expect(cards[1].querySelector('time')?.dateTime).toBe('2026-10-25T12:15:00Z');
 for(const [index,card] of cards.entries()){const button=card.querySelector<HTMLButtonElement>('button')!;expect(button.textContent).toBe('View saved source');for(const id of button.getAttribute('aria-describedby')!.split(' '))expect(document.getElementById(id)?.closest('.conversation-material-card')).toBe(card);await act(async()=>button.click());expect(source).toHaveBeenLastCalledWith(index===0?'source-one':'source-two');}
 expect(host.querySelectorAll('.team-turn')).toHaveLength(3);expect(host.querySelectorAll('.messages-delivery')).toHaveLength(presentation==='messages'?1:0);expect(action).not.toHaveBeenCalled();expect(check).not.toHaveBeenCalled();
});
it('withholds stale unavailable labels and handles missing saved time without presenting it as a reply',async()=>{
 await render('messages',{...projection,turns:[],entries:[{kind:'material',sourceKind:'ehr',id:'source:a',sourceId:'a',label:'Private old label',createdAt:'invalid',state:'unavailable'}]});expect(host.textContent).toContain('Unavailable — check access');expect(host.textContent).toContain('Save time unavailable');expect(host.textContent).not.toContain('Private old label');expect(host.querySelector('time')).toBeNull();expect(host.querySelector('.team-turn')).toBeNull();expect(host.querySelector('.messages-delivery')).toBeNull();
});
it.each(['locked','busy','recoveryBlocked'] as const)('blocks material selection under %s without dispatching another action',async gate=>{
 for(const sourceKind of ['ehr','calendar-import','gmail'] as const){const value:ConversationProjection={...projection,entries:[{kind:'material',sourceKind,id:'source:a',sourceId:'a',label:'Reviewed snapshot',createdAt:'2026-10-25T12:00:00Z',state:'current'}]};await act(async()=>root.render(<ConversationEntries projection={value} latestSourceRevision={2} busy={gate==='busy'} recoveryBlocked={gate==='recoveryBlocked'} locked={gate==='locked'} onWork={()=>{}} onSource={source} onCheck={check} onAction={action}/>));const button=host.querySelector<HTMLButtonElement>('.conversation-material-card button')!;expect(button.disabled).toBe(true);await act(async()=>button.click());expect(source).not.toHaveBeenCalled();expect(action).not.toHaveBeenCalled();expect(check).not.toHaveBeenCalled();}
});

it.each(['messages','workspace'] as const)('renders only calendar file metadata in %s, masks unavailable labels, and opens the exact source',async presentation=>{
 const material=(id:string,state:'current'|'unavailable')=>({kind:'material' as const,sourceKind:'calendar-import' as const,id:`source:${id}`,sourceId:id,label:state==='current'?'Imported calendar snapshot':'Private stale event label',createdAt:state==='current'?'2026-10-25T12:00:00Z':'invalid',state});
 await render(presentation,{...projection,entries:[projection.entries[0],material('calendar-one','current'),material('calendar-two','unavailable'),...projection.entries.slice(1)]});
 const cards=[...host.querySelectorAll<HTMLElement>('[aria-label="Saved calendar file summary"]')];expect(cards).toHaveLength(2);expect(cards[0].querySelector('time')?.dateTime).toBe('2026-10-25T12:00:00Z');expect(cards[1].querySelector('time')).toBeNull();expect(cards[1].textContent).toContain('Save time unavailable');expect(cards[1].textContent).toContain('Unavailable calendar file summary');expect(cards[1].textContent).not.toContain('Private stale event');
 for(const [index,card] of cards.entries()){expect(card.textContent).toContain('File snapshot only');expect(card.textContent).not.toContain('Atlas');const control=card.querySelector<HTMLButtonElement>('button')!;expect(control.textContent).toBe('View saved source');for(const id of control.getAttribute('aria-describedby')!.split(' '))expect(document.getElementById(id)?.closest('.conversation-material-card')).toBe(card);await act(async()=>control.click());expect(source).toHaveBeenLastCalledWith(index===0?'calendar-one':'calendar-two');}
 expect(host.querySelectorAll('.team-turn')).toHaveLength(3);expect(host.querySelectorAll('.messages-delivery')).toHaveLength(presentation==='messages'?1:0);expect(action).not.toHaveBeenCalled();expect(check).not.toHaveBeenCalled();
});

it.each(['messages','workspace'] as const)('renders exact Outlook source actions in %s and masks unavailable subjects independently of projection',async presentation=>{
 const material=(id:string,state:'current'|'unavailable')=>({kind:'material' as const,sourceKind:'outlook' as const,id:`source:${id}`,sourceId:id,label:'Outlook: Private invented subject',createdAt:'2026-10-25T12:00:00Z',state});
 await render(presentation,{...projection,entries:[projection.entries[0],material('email-one','current'),material('email-two','unavailable'),...projection.entries.slice(1)]});
 const cards=[...host.querySelectorAll<HTMLElement>('[aria-label="Saved Outlook email"]')];expect(cards).toHaveLength(2);expect(cards[0].textContent).toContain('Outlook: Private invented subject');expect(cards[1].textContent).toContain('Unavailable email source');expect(cards[1].textContent).not.toContain('Private invented subject');
 for(const [index,card] of cards.entries()){const control=card.querySelector<HTMLButtonElement>('button')!;expect(control.textContent).toBe('View saved source');for(const id of control.getAttribute('aria-describedby')!.split(' '))expect(document.getElementById(id)?.closest('.conversation-material-card')).toBe(card);await act(async()=>control.click());expect(source).toHaveBeenLastCalledWith(index===0?'email-one':'email-two');}
 expect(host.querySelectorAll('.team-turn')).toHaveLength(3);expect(host.querySelectorAll('.messages-delivery')).toHaveLength(presentation==='messages'?1:0);expect(action).not.toHaveBeenCalled();expect(check).not.toHaveBeenCalled();
});

it.each(['messages','workspace'] as const)('renders saved Gmail metadata in %s with exact source actions and independently masks unavailable subjects',async presentation=>{
 const material=(id:string,state:'current'|'unavailable')=>({kind:'material' as const,sourceKind:'gmail' as const,id:`source:${id}`,sourceId:id,label:'Google message: Private invented subject',createdAt:state==='current'?'2026-10-26T12:15:00Z':'',state});
 await render(presentation,{...projection,turns:[],entries:[material('gmail-one','current'),material('gmail-two','unavailable')]});const cards=[...host.querySelectorAll<HTMLElement>('[aria-label="Saved Gmail email"]')];expect(cards).toHaveLength(2);expect(cards[0].textContent).toContain('Google message: Private invented subject');expect(cards[0].querySelector('time')?.dateTime).toBe('2026-10-26T12:15:00Z');expect(cards[1].querySelector('time')).toBeNull();expect(cards[1].textContent).toContain('Save time unavailable');expect(cards[1].querySelector('h3')?.textContent).toBe('Unavailable email source');expect(cards[1].textContent).not.toContain('Private invented subject');
 for(const [index,card] of cards.entries()){const control=card.querySelector<HTMLButtonElement>('button')!;expect(card.querySelectorAll('button')).toHaveLength(1);expect(control.textContent).toBe('View saved source');for(const id of control.getAttribute('aria-describedby')!.split(' '))expect(document.getElementById(id)?.closest('.conversation-material-card')).toBe(card);await act(async()=>control.click());expect(source).toHaveBeenLastCalledWith(index===0?'gmail-one':'gmail-two');}
 expect(host.querySelector('.team-turn')).toBeNull();expect(host.querySelector('.messages-delivery')).toBeNull();expect(host.querySelector('.messages-time-separator')).toBeNull();expect(host.querySelector('[role="status"]')).toBeNull();expect(action).not.toHaveBeenCalled();expect(check).not.toHaveBeenCalled();
});

it.each(['messages','workspace'] as const)('renders saved Research metadata in %s with the existing exact-source action',async presentation=>{
 const packet={kind:'material' as const,sourceKind:'research' as const,id:'source:research-one',sourceId:'research-one',label:'Research · public source excerpts',createdAt:'2026-10-25T12:15:00Z',state:'current' as const};await render(presentation,{...projection,entries:[packet]});const card=host.querySelector<HTMLElement>('[aria-label="Saved Research packet"]')!;expect(card).not.toBeNull();expect(card.querySelector('h3')?.textContent).toBe('Research · public source excerpts');expect(card.querySelector('time')?.dateTime).toBe(packet.createdAt);expect(card.textContent).toContain('Saved snapshot available');expect(card.textContent).not.toContain('current research');const control=card.querySelector<HTMLButtonElement>('button')!;for(const id of control.getAttribute('aria-describedby')!.split(' '))expect(document.getElementById(id)?.closest('.conversation-material-card')).toBe(card);await act(async()=>control.click());expect(source).toHaveBeenCalledExactlyOnceWith(packet.sourceId);expect(action).not.toHaveBeenCalled();expect(check).not.toHaveBeenCalled();expect(host.querySelector('.team-turn')).toBeNull();expect(host.querySelector('.messages-delivery')).toBeNull();
});

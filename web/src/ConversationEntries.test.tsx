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

import {act,useSyncExternalStore} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {MessagesInbox,NewMessagePicker} from './MessagesPresentation';
import {WorkspaceInboxPreferences} from './session/inbox-preferences';
import {DraftJournal} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {teamFixture,teamUuid} from './team-setup-test-fixture';
import type {ConversationSummary} from './conversations-api';
import type {Workspace} from './workspace-api';
const first:ConversationSummary={workspace_id:teamUuid(900),appointment_id:null,context_label:'Invented sleep notebook',bot:{address:'chief',role:'chief',name:'Chief of Staff',available:true},preview:'Organize invented notes',preview_withheld:false,attention:'needs_review',last_activity_at:new Date().toISOString(),watermark:'opaque',unread:true,manual_unread:false,marker_version:1};
const second:ConversationSummary={...first,workspace_id:teamUuid(901),bot:{address:'follow_up',role:'follow_up',name:'Follow-up',available:true},context_label:'Invented medication note',attention:'idle'};
let root:Root,host:HTMLDivElement,controller:WorkspaceInboxPreferences,journal:DraftJournal,read:ReturnType<typeof vi.fn>,more:ReturnType<typeof vi.fn>,rename:ReturnType<typeof vi.fn>;
function Harness(){const organization=useSyncExternalStore(controller.subscribe,controller.getSnapshot,controller.getSnapshot);
  return <MessagesInbox team={teamFixture()} inbox={{contract_version:1,as_of:new Date().toISOString(),rows:[first,second],next_cursor:'opaque-earlier-page'}} loading={false} locked={false} error="" organization={organization}
    onOpen={()=>{}} onNew={()=>{}} onChief={()=>{}} onRefresh={()=>{}} onMore={()=>more()} onUnread={()=>{}} onSettings={()=>{}} onOrganize={(row,change)=>controller.set(row,change)} onRestoreAll={()=>controller.restoreAll()}
    onInspect={row=>void controller.inspect(row)} onCloseMenu={()=>controller.closeMenu()} onRename={target=>rename(target)} onReloadOrganization={()=>{}}/>;
}
beforeEach(async()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);journal=new DraftJournal(await memoryDraftStorage()({scope:'a'.repeat(64)}));
  read=vi.fn(async()=>({id:first.workspace_id,appointment_id:null,label:first.context_label,revision:1,entries:[],work_candidates:[],notebook:{title:first.context_label,title_revision:3,created_at:first.last_activity_at}} satisfies Workspace));
  controller=new WorkspaceInboxPreferences(read);await controller.bind({identity:{mode:'clerk_jwt',getToken:async()=>null},recovery:{journal,recoveryScope:'a'.repeat(64),authorize:async()=>{}},current:()=>true,denied:()=>{}});
  more=vi.fn();rename=vi.fn();host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<Harness/>));
});
afterEach(async()=>{await act(async()=>root.unmount());journal.close();host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
const button=(text:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>item.textContent===text)!;
const click=async(text:string)=>{await act(async()=>button(text).click());};
async function menu(){await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row-menu')!.click());}
it('searches loaded results honestly and offers the earlier-results path',async()=>{
  const input=host.querySelector<HTMLInputElement>('input[type="search"]')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'Missing invented text');input.dispatchEvent(new Event('input',{bubbles:true}));});
  expect(host.textContent).toContain('0 matches among 2 loaded conversations. Load earlier conversations to search more.');expect(host.querySelectorAll('.messages-row')).toHaveLength(0);expect(read).not.toHaveBeenCalled();
  await click('Load earlier conversations');expect(more).toHaveBeenCalledOnce();
});
it('uses one row menu and keeps hidden chats discoverable and restorable',async()=>{
  expect(button('Mark unread')).toBeUndefined();expect(host.querySelectorAll('.messages-row-menu')).toHaveLength(2);
  await menu();expect(host.querySelectorAll('[role="dialog"]')).toHaveLength(1);await click('Hide conversation');
  expect(host.querySelector('[role="dialog"]')).toBeNull();expect(host.querySelectorAll('.messages-row')).toHaveLength(1);expect(document.activeElement).toBe(host.querySelector('h1'));
  await click('Hidden conversations (1)');expect(host.querySelectorAll('.messages-row')).toHaveLength(1);expect(host.textContent).toContain(first.context_label);
  await menu();await click('Restore conversation');expect(controller.getSnapshot().value.items).toEqual([]);
  await click('Back to conversations');expect(host.querySelectorAll('.messages-row')).toHaveLength(2);
});
it('shows a storage failure without claiming the conversation was hidden',async()=>{
  vi.spyOn(journal,'persist').mockRejectedValueOnce(new Error('Invented unavailable storage'));
  await menu();await click('Hide conversation');expect(host.querySelector('[role="dialog"]')).not.toBeNull();expect(host.querySelectorAll('.messages-row')).toHaveLength(2);expect(host.querySelector('[role="dialog"] [role="alert"]')?.textContent).toContain('previous conversation organization is retained');
});
it('opens the existing rename workflow only with verified notebook metadata',async()=>{
  await menu();await vi.waitFor(()=>expect(button('Rename notebook')).toBeTruthy());await click('Rename notebook');
  expect(rename).toHaveBeenCalledExactlyOnceWith({workspaceId:first.workspace_id,title:first.context_label,titleRevision:3});expect(host.querySelector('[role="dialog"]')).toBeNull();
});
it.each([false,true])('keeps the independent beta focused on Chief when model readiness is %s',async enabled=>{
  vi.stubEnv('VITE_WORKSPACE_FEATURE_PROFILE','independent-beta-v1');
  const team=teamFixture(),choose=vi.fn();team.llm.enabled=enabled;
  await act(async()=>root.render(<NewMessagePicker team={team} locked={false} onChoose={choose} onClose={()=>{}}/>));
  const choices=host.querySelectorAll<HTMLButtonElement>('.messages-bot-choices button');
  expect(choices).toHaveLength(1);expect(choices[0].textContent).toMatch(/chief/i);
  expect(host.textContent).not.toContain('recording');
  await act(async()=>choices[0].click());expect(choose).toHaveBeenCalledExactlyOnceWith('chief');
});

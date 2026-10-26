import {act,type ComponentProps} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {MessagesInbox} from './MessagesPresentation';
import {teamFixture,teamUuid} from './team-setup-test-fixture';
import {emptyConversationPreferences} from './conversation-preferences';
import type {ConversationSummary} from './conversations-api';

type Props=ComponentProps<typeof MessagesInbox>;
const first:ConversationSummary={workspace_id:teamUuid(900),appointment_id:null,context_label:'Invented sleep notebook',bot:{address:'chief',role:'chief',name:'Chief of Staff',available:true},preview:'Organize invented notes',preview_withheld:false,attention:'needs_review',last_activity_at:'2026-10-26T12:00:00Z',watermark:'opaque',unread:true,manual_unread:false,marker_version:1};
const second:ConversationSummary={...first,workspace_id:teamUuid(901),bot:{address:'follow_up',role:'follow_up',name:'Follow-up',available:true},context_label:'Invented medication note',attention:'idle'};
let root:Root,host:HTMLDivElement,props:Props;
beforeEach(async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('scrollY',0);
 props={identity:{mode:'clerk_jwt',getToken:async()=>null},team:teamFixture(),inbox:{contract_version:1,as_of:first.last_activity_at,rows:[first,second],next_cursor:'earlier'},loading:false,locked:false,error:'',organization:{value:emptyConversationPreferences(),ready:true,busy:false,error:'',inspecting:false,rename:null,renameError:''},onOpen:vi.fn(),onNew:vi.fn(),onChief:vi.fn(),onRefresh:vi.fn(),onMore:vi.fn(),onUnread:vi.fn(),onSettings:vi.fn(),onOrganize:vi.fn(async()=>true),onRestoreAll:vi.fn(async()=>true),onInspect:vi.fn(),onCloseMenu:vi.fn(),onRename:vi.fn(),onReloadOrganization:vi.fn()};
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await render();
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
async function render(change:Partial<Props>={}){props={...props,...change};await act(async()=>root.render(<MessagesInbox {...props}/>));}
const input=()=>host.querySelector<HTMLInputElement>('input[type="search"]')!;
const button=(text:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(value=>value.textContent===text);
const visible=()=>!!input()&&!input().closest('[hidden]');
async function scroll(top:number,target:HTMLElement|Window=host){await act(async()=>{if(target===window)vi.stubGlobal('scrollY',top);else (target as HTMLElement).scrollTop=top;target.dispatchEvent(new Event('scroll'));});}
async function type(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input(),value);input().dispatchEvent(new Event('input',{bubbles:true}));});}
async function click(text:string){expect(button(text)).toBeTruthy();await act(async()=>button(text)!.click());}
function noRequests(){for(const callback of [props.onOpen,props.onNew,props.onChief,props.onRefresh,props.onMore,props.onUnread,props.onOrganize,props.onRestoreAll,props.onInspect])expect(callback).not.toHaveBeenCalled();}

it('compacts an empty unfocused search while scrolling and Search reopens and focuses it',async()=>{
 expect(visible()).toBe(true);await scroll(180);
 expect(button('Search')).toBeTruthy();expect(visible()).toBe(false);
 expect(button('Search')!.getAttribute('aria-label')).toBe('Search conversations');
 expect(button('Search')!.getAttribute('aria-controls')).toBe(input().id);
 await click('Search');expect(visible()).toBe(true);expect(document.activeElement).toBe(input());expect(input().value).toBe('');
 noRequests();
});
it('keeps focused and nonempty searches visible with the loaded-page explanation',async()=>{
 await act(async()=>input().focus());await scroll(240);expect(visible()).toBe(true);
 await type('medication');await act(async()=>input().blur());await scroll(400,window);
 expect(visible()).toBe(true);expect(input().value).toBe('medication');expect(button('Search')).toBeUndefined();
 const status=host.querySelector('.messages-inbox-tools [role="status"]');
 expect(status?.textContent).toBe('1 match among 2 loaded conversations. Load earlier conversations to search more.');
 expect(host.querySelectorAll('.messages-row')).toHaveLength(1);noRequests();
});
it('preserves an exact query through refresh and loading earlier results without changing row actions',async()=>{
 await type('  medication  ');await scroll(240);await click('Load earlier conversations');await click('Refresh conversations');
 expect(props.onMore).toHaveBeenCalledOnce();expect(props.onRefresh).toHaveBeenCalledOnce();
 const third={...second,workspace_id:teamUuid(902),context_label:'Another invented medication note'};
 await render({inbox:{...props.inbox!,rows:[first,second,third],next_cursor:null}});
 expect(input().value).toBe('  medication  ');expect(visible()).toBe(true);
 expect(host.querySelector('.messages-inbox-tools [role="status"]')?.textContent).toBe('2 matches among 3 loaded conversations.');
 expect(button('Load earlier conversations')).toBeUndefined();expect(props.onOpen).not.toHaveBeenCalled();expect(props.onUnread).not.toHaveBeenCalled();
 await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row')!.click());expect(props.onOpen).toHaveBeenCalledExactlyOnceWith(second);
});
it('keeps clearing visible until focus leaves, treats whitespace as nonempty, and expands at the top',async()=>{
 await type(' ');await scroll(180);expect(visible()).toBe(true);expect(input().value).toBe(' ');
 await act(async()=>input().focus());await type('');expect(visible()).toBe(true);
 await act(async()=>input().blur());expect(visible()).toBe(false);
 await click('Search');expect(input().value).toBe('');await act(async()=>input().blur());expect(visible()).toBe(false);
 await scroll(0);expect(visible()).toBe(true);expect(document.activeElement).not.toBe(input());noRequests();
});
it('ignores unrelated scrolling and keeps pull-to-refresh independent',async()=>{
 const other=document.createElement('div');document.body.append(other);
 try{await scroll(200,other);expect(visible()).toBe(true);await scroll(180);expect(visible()).toBe(false);await scroll(0);expect(visible()).toBe(true);
  const section=host.querySelector('.messages-inbox')!;
  for(const [kind,y] of [['touchstart',100],['touchmove',210],['touchend',210]] as const){
   const event=new Event(kind,{bubbles:true,cancelable:true}),touch={identifier:1,clientX:100,clientY:y};
   Object.defineProperties(event,{touches:{value:kind==='touchend'?[]:[touch]},changedTouches:{value:[touch]}});await act(async()=>section.dispatchEvent(event));
  }
  expect(props.onRefresh).toHaveBeenCalledOnce();expect(input().value).toBe('');expect(visible()).toBe(true);expect(props.onMore).not.toHaveBeenCalled();expect(props.onUnread).not.toHaveBeenCalled();
 }finally{other.remove();}
});
it.each(['identity','scope'] as const)('clears the prior owner query and compaction when %s changes',async kind=>{
 await type('old owner query');await scroll(180);
 await render(kind==='identity'?{identity:{mode:'clerk_jwt',getToken:async()=>null}}:{team:{...props.team!,recovery_scope:'b'.repeat(64)}});
 expect(input().value).toBe('');expect(visible()).toBe(true);expect(host.textContent).not.toContain('0 matches');
 expect(document.activeElement).not.toBe(input());noRequests();
});

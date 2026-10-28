import {act,type ComponentProps} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {MessagesInbox} from './MessagesPresentation';
import {teamFixture,teamUuid} from './team-setup-test-fixture';
import {emptyConversationPreferences} from './conversation-preferences';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
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
async function scroll(top:number,target:HTMLElement|Window=host){await act(async()=>{if(target===window)vi.stubGlobal('scrollY',top);else (target as HTMLElement).scrollTop=top;(target===window?document:target).dispatchEvent(new Event('scroll'));});}
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
function keyboardGeometry(){
 let toolsBottom=86,rowTop=-4,next=0;
 const frames=new Map<number,FrameRequestCallback>();
 vi.stubGlobal('requestAnimationFrame',(callback:FrameRequestCallback)=>{frames.set(++next,callback);return next;});
 vi.stubGlobal('cancelAnimationFrame',(id:number)=>frames.delete(id));
 const tools=host.querySelector<HTMLElement>('.messages-inbox-tools')!,row=host.querySelector<HTMLButtonElement>('.messages-row')!;
 const rect=(top:number,height:number)=>({top,bottom:top+height,left:0,right:320,width:320,height,x:0,y:top,toJSON:()=>({})});
 vi.spyOn(tools,'getBoundingClientRect').mockImplementation(()=>rect(0,toolsBottom));
 vi.spyOn(row,'getBoundingClientRect').mockImplementation(()=>rect(rowTop,1004));
 const move=vi.spyOn(window,'scrollTo').mockImplementation((optionsOrX?:ScrollToOptions|number,y?:number)=>{
  const top=typeof optionsOrX==='number'?y??0:optionsOrX?.top??window.scrollY;
  rowTop+=window.scrollY-top;vi.stubGlobal('scrollY',top);
 });
 return {row,move,setToolsBottom:(value:number)=>{toolsBottom=value;},setRowTop:(value:number)=>{rowTop=value;},retained:()=>[...frames.values()],flush:async()=>{await act(async()=>{const pending=[...frames.values()];frames.clear();for(const callback of pending)callback(0);});}};
}
async function tabTo(target:HTMLElement,shiftKey=false){
 await act(async()=>{document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey,bubbles:true}));target.focus();});
}

it('keeps the leading keyboard-focused conversation below the measured sticky search tools',async()=>{
 const view=keyboardGeometry();await scroll(240,window);expect(window.scrollY).toBe(240);await click('Search');
 await tabTo(view.row);expect(visible()).toBe(false);
 // Layout can change when the input compacts; measure the final toolbar, not
 // its old input height or a fixed pixel assumption. The row is taller than
 // the viewport, so only its leading title/focus edge needs clearance.
 view.setToolsBottom(118);await view.flush();
 expect(view.move).toHaveBeenCalledExactlyOnceWith({top:110,left:window.scrollX,behavior:'instant'});
 expect(view.row.getBoundingClientRect().top).toBe(126);
 expect(document.activeElement).toBe(view.row);expect(input().value).toBe('');noRequests();
});

it('clears the focused row through its actual nested scroll owner without moving the document',async()=>{
 const view=keyboardGeometry();host.style.overflowY='auto';Object.defineProperties(host,{scrollHeight:{value:1800},clientHeight:{value:400}});
 await scroll(300);await click('Search');await tabTo(view.row,true);await view.flush();
 expect(host.scrollTop).toBe(202);expect(view.move).not.toHaveBeenCalled();expect(document.activeElement).toBe(view.row);noRequests();
});

it('leaves already visible keyboard focus and ordinary pointer/programmatic row focus in place',async()=>{
 const view=keyboardGeometry();await scroll(240,window);await click('Search');view.setRowTop(130);
 await tabTo(view.row);await view.flush();expect(view.move).not.toHaveBeenCalled();
 view.setRowTop(-4);await click('Search');
 await act(async()=>{input().dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true}));view.row.dispatchEvent(new Event('pointerdown',{bubbles:true}));view.row.focus();});
 await view.flush();expect(view.move).not.toHaveBeenCalled();
 await click('Search');await act(async()=>view.row.focus());await view.flush();expect(view.move).not.toHaveBeenCalled();noRequests();
});

it.each(['identity','scope','focus','pointer','wheel','key','blur','hidden','removed'] as const)('cancels pending keyboard clearance after %s changes',async reason=>{
 const view=keyboardGeometry();await scroll(240,window);await click('Search');await tabTo(view.row);
 if(reason==='identity')await render({identity:{mode:'clerk_jwt',getToken:async()=>null}});
 else if(reason==='scope')await render({team:{...props.team!,recovery_scope:'c'.repeat(64)}});
 else if(reason==='focus')await act(async()=>button('Refresh conversations')!.focus());
 else if(reason==='pointer'||reason==='wheel')host.dispatchEvent(new Event(reason==='pointer'?'pointerdown':'wheel',{bubbles:true}));
 else if(reason==='key')document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
 else if(reason==='blur')window.dispatchEvent(new Event('blur'));
 else if(reason==='hidden')host.hidden=true;
 else await act(async()=>root.render(<p>Another view</p>));
 await view.flush();expect(view.move).not.toHaveBeenCalled();noRequests();
});

it('consumes Tab on any next focus and never lends it to later source-return focus',async()=>{
 const view=keyboardGeometry();await scroll(240,window);await click('Search');
 await tabTo(button('Refresh conversations')!);await act(async()=>view.row.focus());await view.flush();expect(view.move).not.toHaveBeenCalled();
 await click('Search');await act(async()=>{input().dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true}));input().dispatchEvent(new KeyboardEvent('keyup',{key:'Tab',bubbles:true}));view.row.focus();});
 await view.flush();expect(view.move).not.toHaveBeenCalled();noRequests();
});

it('clears a pending Tab on an unfocused blur and clamps correction at the top without horizontal movement',async()=>{
 const view=keyboardGeometry();await scroll(240,window);await click('Search');
 await act(async()=>{input().dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true}));input().blur();view.row.focus();});
 await view.flush();expect(view.move).not.toHaveBeenCalled();
 await click('Search');await type('Chief');vi.stubGlobal('scrollX',47);vi.stubGlobal('scrollY',30);
 await tabTo(view.row);await view.flush();
 expect(view.move).toHaveBeenCalledExactlyOnceWith({top:0,left:47,behavior:'instant'});
 expect(input().value).toBe('Chief');expect(visible()).toBe(true);noRequests();
});

it('withholds a retained keyboard frame across native suspension and resume',async()=>{
 const view=keyboardGeometry();await scroll(240,window);await click('Search');await tabTo(view.row);
 const retained=view.retained();expect(retained).toHaveLength(1);
 await act(async()=>{notifyNativeWorkspaceForeground(props.identity!,false);notifyNativeWorkspaceForeground(props.identity!,true);for(const callback of retained)callback(0);});
 expect(view.move).not.toHaveBeenCalled();expect(document.activeElement).toBe(view.row);noRequests();
});

it.each(['identity','scope','unmount'] as const)('withholds a retained old frame after %s replacement, even if the same view returns',async reason=>{
 const view=keyboardGeometry(),original=props;await scroll(240,window);await click('Search');await tabTo(view.row);
 const retained=view.retained();expect(retained).toHaveLength(1);
 if(reason==='identity')await render({identity:{mode:'clerk_jwt',getToken:async()=>null}});
 else if(reason==='scope')await render({team:{...props.team!,recovery_scope:'d'.repeat(64)}});
 else await act(async()=>root.render(<p>Another view</p>));
 await render(original);await act(async()=>{host.querySelector<HTMLButtonElement>('.messages-row')!.focus();for(const callback of retained)callback(0);});
 expect(view.move).not.toHaveBeenCalled();noRequests();
});

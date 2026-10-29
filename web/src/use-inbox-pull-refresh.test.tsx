import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {useInboxPullRefresh} from './use-inbox-pull-refresh';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

let root:Root,host:HTMLDivElement,refresh:ReturnType<typeof vi.fn>;
function Inbox({disabled=false,scope='invented-account-a',identity}:{disabled?:boolean;scope?:string;identity?:AuthenticatedWorkspaceIdentity}){
  const pull=useInboxPullRefresh({disabled,scope,onRefresh:refresh,identity});
  return <section ref={pull.ref} data-distance={pull.distance} data-ready={pull.ready}><button>Saved conversation</button><input aria-label="Search"/><div role="dialog">Actions</div></section>;
}
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);refresh=vi.fn();host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
async function render(props:Parameters<typeof Inbox>[0]={}){await act(async()=>root.render(<Inbox {...props}/>));}
const section=()=>host.querySelector('section')!;
const finger=(x:number,y:number,id=1)=>({identifier:id,clientX:x,clientY:y});
async function touch(type:string,x:number,y:number,{target=section(),count=1,cancelable=true,id=1}:{target?:Element;count?:number;cancelable?:boolean;id?:number}={}){
  const event=new Event(type,{bubbles:true,cancelable});
  Object.defineProperties(event,{touches:{value:type==='touchend'?[]:Array.from({length:count},(_,i)=>finger(x,y,id+i))},changedTouches:{value:[finger(x,y,id)]}});
  await act(async()=>target.dispatchEvent(event));return event;
}
async function pull(){await touch('touchstart',100,100);await touch('touchmove',100,205);return touch('touchend',100,205);}

it('refreshes once on deliberate release, withholds until release and suppresses the row tap',async()=>{
  await render();await touch('touchstart',100,100,{target:section().querySelector('button')!});
  const move=await touch('touchmove',102,205);expect(move.defaultPrevented).toBe(true);expect(section().dataset.ready).toBe('true');expect(refresh).not.toHaveBeenCalled();
  const end=await touch('touchend',102,205);expect(end.defaultPrevented).toBe(true);expect(refresh).toHaveBeenCalledOnce();expect(section().dataset.distance).toBe('0');
  await touch('touchend',102,205);expect(refresh).toHaveBeenCalledOnce();
});
it('does not turn short pulls, horizontal/back gestures or normal scrolling into refresh',async()=>{
  await render();
  for(const [x,dy,dx] of [[100,30,0],[100,80,100],[100,-100,0],[10,110,0],[window.innerWidth-10,110,0]]){
    await touch('touchstart',x,150);await touch('touchmove',x+dx,150+dy);await touch('touchend',x+dx,150+dy);
  }
  host.scrollTop=60;await pull();host.scrollTop=0;expect(refresh).not.toHaveBeenCalled();
});
it('leaves editing and dialogs untouched and does not claim browser-owned moves',async()=>{
  await render();
  for(const target of [section().querySelector('input')!,section().querySelector('[role="dialog"]')!]){
    await touch('touchstart',100,100,{target});expect((await touch('touchmove',100,210,{target})).defaultPrevented).toBe(false);await touch('touchend',100,210,{target});
  }
  await touch('touchstart',100,100);await touch('touchmove',100,210,{cancelable:false});await touch('touchend',100,210);expect(refresh).not.toHaveBeenCalled();
});
it('cancels on multi-touch, touch cancellation, account replacement and a newly locked screen',async()=>{
  await render();
  await touch('touchstart',100,100);await touch('touchmove',100,210,{count:2});await touch('touchend',100,210);
  await touch('touchstart',100,100);await touch('touchmove',100,210);await touch('touchcancel',100,210);await touch('touchend',100,210);
  await touch('touchstart',100,100);await touch('touchmove',100,210);await render({scope:'invented-account-b'});await touch('touchend',100,210);
  await touch('touchstart',100,100);await touch('touchmove',100,210);await render({disabled:true});await touch('touchend',100,210);await pull();expect(refresh).not.toHaveBeenCalled();
});
it('keeps one request in flight and allows another pull after that request settles',async()=>{
  let release!:()=>void;refresh.mockReturnValueOnce(new Promise<void>(resolve=>{release=resolve;}));await render();
  await pull();await pull();expect(refresh).toHaveBeenCalledOnce();await act(async()=>release());await pull();expect(refresh).toHaveBeenCalledTimes(2);
});
it('clears an armed gesture when backgrounded or when scrolling moves away from the top',async()=>{
  await render();await touch('touchstart',100,100);await touch('touchmove',100,210);
  await act(async()=>window.dispatchEvent(new Event('blur')));await touch('touchend',100,210);
  await touch('touchstart',100,100);await touch('touchmove',100,210);host.scrollTop=40;await touch('touchend',100,210);expect(refresh).not.toHaveBeenCalled();
});
it('drops an armed pull on native suspension even when the document stays visible',async()=>{
  const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};await render({identity});
  expect(document.visibilityState).toBe('visible');await touch('touchstart',100,100);await touch('touchmove',100,210);
  await act(async()=>notifyNativeWorkspaceForeground(identity,false));await touch('touchend',100,210);await pull();expect(refresh).not.toHaveBeenCalled();
  await act(async()=>notifyNativeWorkspaceForeground(identity,true));await touch('touchend',100,210);expect(refresh).not.toHaveBeenCalled();await pull();expect(refresh).toHaveBeenCalledOnce();
});

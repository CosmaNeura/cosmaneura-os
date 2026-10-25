import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {useMobileChatFrame} from './MobileChatFrame';

let root:Root,host:HTMLDivElement,observers:{callback:()=>void;disconnect:ReturnType<typeof vi.fn>}[];
let height=1000,visible=200;
let controls:ReturnType<typeof useMobileChatFrame>;
function Frame({owner,messages='one',current=true,active=true,historyVisible=true,scope='invented-workspace:chief',arrivals,onBottomVisible}:{owner:object;messages?:string;current?:boolean;active?:boolean;historyVisible?:boolean;scope?:string;arrivals?:string[];onBottomVisible?:()=>void}){
  const frame=useMobileChatFrame({active,visible:historyVisible,owner,scope,messages,isCurrent:()=>current,arrivals,onBottomVisible});controls=frame;
  return <div ref={frame.scrollRef} onScroll={frame.onScroll} data-new-messages={frame.newMessages}>Invented saved conversation<button onClick={frame.jumpToLatest}>New messages</button></div>;
}
beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);height=1000;visible=200;observers=[];
  vi.stubGlobal('ResizeObserver',class{entry:{callback:()=>void;disconnect:ReturnType<typeof vi.fn>};constructor(callback:()=>void){this.entry={callback,disconnect:vi.fn()};observers.push(this.entry);}observe(){}disconnect(){this.entry.disconnect();}});
  vi.spyOn(HTMLElement.prototype,'scrollHeight','get').mockImplementation(()=>height);
  vi.spyOn(HTMLElement.prototype,'clientHeight','get').mockImplementation(()=>visible);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
const scroller=()=>host.firstElementChild as HTMLDivElement;
async function render(props:Parameters<typeof Frame>[0]){await act(async()=>root.render(<Frame {...props}/>));}
async function scroll(top:number){await act(async()=>{scroller().scrollTop=top;scroller().dispatchEvent(new Event('scroll',{bubbles:true}));});}

it('keeps an older message anchored when a new saved reply arrives away from the bottom',async()=>{
  const owner={};await render({owner});expect(scroller().scrollTop).toBe(800);
  await scroll(200);height=1400;await render({owner,messages:'one:actual-reply'});
  expect(scroller().scrollTop).toBe(200);
});
it('follows actual new messages near the bottom and the available WK height after keyboard resize',async()=>{
  const owner={};await render({owner});await scroll(760);
  height=1400;await render({owner,messages:'one,two:actual-reply'});expect(scroller().scrollTop).toBe(1200);
  visible=120;await act(async()=>observers[0].callback());expect(scroller().scrollTop).toBe(1280);
});
it('does not scroll for unrelated renders or use document scrolling',async()=>{
  const documentScroll=vi.spyOn(window,'scrollTo');const owner={};await render({owner});
  scroller().scrollTop=780;height=1400;await render({owner});
  expect(scroller().scrollTop).toBe(780);expect(documentScroll).not.toHaveBeenCalled();
});
it('withholds obsolete observer work after owner replacement, authority loss and unmount',async()=>{
  const first={};await render({owner:first});const obsolete=observers[0];
  await render({owner:{}});expect(obsolete.disconnect).toHaveBeenCalledOnce();
  scroller().scrollTop=200;await act(async()=>obsolete.callback());expect(scroller().scrollTop).toBe(200);
  const current={};await render({owner:current,current:false,messages:'new saved reply'});expect(scroller().scrollTop).toBe(200);
  const last=observers.at(-1)!;const element=scroller();await act(async()=>root.unmount());root=createRoot(host);
  element.scrollTop=10;last.callback();expect(element.scrollTop).toBe(10);expect(last.disconnect).toHaveBeenCalledOnce();
});
it('leaves ordinary web presentation untouched',async()=>{
  await render({owner:{},active:false});expect(scroller().scrollTop).toBe(0);expect(observers).toHaveLength(0);
});
it('counts arriving replies above the bottom and acknowledges only after an explicit jump',async()=>{
  const owner={},seen=vi.fn();await render({owner,arrivals:['question'],onBottomVisible:seen});seen.mockClear();
  await scroll(200);height=1400;await render({owner,messages:'question:reply',arrivals:['question','reply'],onBottomVisible:seen});
  expect(scroller().scrollTop).toBe(200);expect(scroller().dataset.newMessages).toBe('1');expect(seen).not.toHaveBeenCalled();
  await act(async()=>scroller().querySelector('button')!.click());
  expect(scroller().scrollTop).toBe(1200);expect(scroller().dataset.newMessages).toBe('0');expect(seen).toHaveBeenCalled();
});
it('does not count busy wording as a new message or acknowledge a hidden history',async()=>{
  const owner={},seen=vi.fn();await render({owner,arrivals:['question'],onBottomVisible:seen});await scroll(200);seen.mockClear();
  await render({owner,messages:'busy wording changed',arrivals:['question'],onBottomVisible:seen});
  expect(scroller().dataset.newMessages).toBe('0');expect(seen).not.toHaveBeenCalled();
  visible=0;await render({owner,messages:'reply',arrivals:['question','reply'],onBottomVisible:seen});
  await act(async()=>scroller().querySelector('button')!.click());expect(seen).not.toHaveBeenCalled();
});

it('preserves an explicit near-bottom return through queued scrolls and transient resize clamping',async()=>{
 const owner={},seen=vi.fn();height=3593;visible=149;await render({owner,arrivals:['reply'],onBottomVisible:seen});await scroll(3423);seen.mockClear();
 await act(async()=>controls.restoreReadingPosition(3423));await scroll(3423);await act(async()=>observers[0].callback());expect(scroller().scrollTop).toBe(3423);expect(seen).not.toHaveBeenCalled();
 height=3566;await act(async()=>observers[0].callback());expect(scroller().scrollTop).toBe(3417);await scroll(3417);
 height=3593;await act(async()=>observers[0].callback());expect(scroller().scrollTop).toBe(3423);await scroll(3423);
 visible=0;await scroll(0);await act(async()=>observers[0].callback());visible=149;await act(async()=>observers[0].callback());expect(scroller().scrollTop).toBe(3423);
});

it('keeps an arriving reply unread above a restored position until the reader jumps to it',async()=>{
 const owner={},seen=vi.fn();await render({owner,arrivals:['one'],onBottomVisible:seen});await act(async()=>controls.restoreReadingPosition(779));seen.mockClear();
 height=1300;await render({owner,messages:'one,two',arrivals:['one','two'],onBottomVisible:seen});await scroll(779);await act(async()=>observers[0].callback());
 expect(scroller().scrollTop).toBe(779);expect(scroller().dataset.newMessages).toBe('1');expect(seen).not.toHaveBeenCalled();
 await act(async()=>controls.jumpToLatest());expect(scroller().scrollTop).toBe(1100);expect(scroller().dataset.newMessages).toBe('0');expect(seen).toHaveBeenCalled();
 height=1400;await act(async()=>observers[0].callback());expect(scroller().scrollTop).toBe(1200);
});

it.each(['scroll','compose'] as const)('resumes ordinary near-bottom following after the reader chooses to %s without an immediate jump',async action=>{
 const owner={};await render({owner});await act(async()=>controls.restoreReadingPosition(779));
 if(action==='scroll')await scroll(785);else await act(async()=>controls.releaseReadingPosition());
 expect(scroller().scrollTop).toBe(action==='scroll'?785:779);height=1400;await render({owner,messages:'actual new reply'});expect(scroller().scrollTop).toBe(1200);
});

it('does not start following when composing or scrolling resumes far from the bottom',async()=>{
 const owner={};await render({owner});await act(async()=>controls.restoreReadingPosition(200));await act(async()=>controls.releaseReadingPosition());height=1400;await render({owner,messages:'one,two'});expect(scroller().scrollTop).toBe(200);
 await act(async()=>controls.restoreReadingPosition(1179));await scroll(400);height=1800;await render({owner,messages:'one,two,three'});expect(scroller().scrollTop).toBe(400);
});

it.each(['owner','scope','inactive'] as const)('rejects captured restore and release callbacks after %s replacement, even when the former identity returns',async change=>{
 const first={},second={};await render({owner:first});const stale=controls;await act(async()=>stale.restoreReadingPosition(779));
 await render({owner:change==='owner'?second:first,scope:change==='scope'?'another-workspace:chief':undefined,active:change!=='inactive'});await render({owner:first});await act(async()=>controls.restoreReadingPosition(779));
 await act(async()=>{stale.restoreReadingPosition(300);stale.releaseReadingPosition();});height=1400;await act(async()=>observers.at(-1)!.callback());expect(scroller().scrollTop).toBe(779);
});

it('withholds restore and release after authority loss or unmount',async()=>{
 const owner={};await render({owner});const former=controls;await act(async()=>former.restoreReadingPosition(779));await render({owner,current:false});
 await act(async()=>{former.restoreReadingPosition(300);former.releaseReadingPosition();});expect(scroller().scrollTop).toBe(779);await render({owner});height=1400;await act(async()=>observers.at(-1)!.callback());expect(scroller().scrollTop).toBe(779);
 const element=scroller(),last=controls;await act(async()=>root.unmount());root=createRoot(host);element.scrollTop=120;last.restoreReadingPosition(300);last.releaseReadingPosition();expect(element.scrollTop).toBe(120);
});

it.each(['wheel','touchmove','keydown'])('releases a clamped return on %s intent even without a changed scroll position',async event=>{
 const owner={};await render({owner});await act(async()=>controls.restoreReadingPosition(900));expect(scroller().scrollTop).toBe(800);
 await act(async()=>scroller().dispatchEvent(event==='keydown'?new KeyboardEvent('keydown',{key:'PageDown',bubbles:true}):event==='wheel'?new WheelEvent('wheel',{deltaY:20,bubbles:true}):new Event('touchmove',{bubbles:true})));
 height=1400;await render({owner,messages:'actual reply'});expect(scroller().scrollTop).toBe(1200);
});

it('ignores same-node task scroll and input, then restores before acknowledging a returned history',async()=>{
 const owner={},seen=vi.fn();await render({owner,arrivals:['one'],onBottomVisible:seen});await act(async()=>controls.restoreReadingPosition(779));seen.mockClear();
 await render({owner,historyVisible:false,messages:'source task',arrivals:['one'],onBottomVisible:seen});await scroll(800);await act(async()=>{scroller().dispatchEvent(new WheelEvent('wheel',{deltaY:20,bubbles:true}));observers[0].callback();});expect(seen).not.toHaveBeenCalled();
 height=1300;await render({owner,historyVisible:false,messages:'source task:reply',arrivals:['one','two'],onBottomVisible:seen});expect(scroller().dataset.newMessages).toBe('1');
 await render({owner,arrivals:['one','two'],onBottomVisible:seen});expect(scroller().scrollTop).toBe(779);expect(seen).not.toHaveBeenCalled();expect(scroller().dataset.newMessages).toBe('1');
});

it('still acknowledges replies that are actually visible at a restored bottom',async()=>{
 const owner={},seen=vi.fn();await render({owner,arrivals:['one'],onBottomVisible:seen});await act(async()=>controls.restoreReadingPosition(800));seen.mockClear();
 await render({owner,messages:'one,two',arrivals:['one','two'],onBottomVisible:seen});expect(scroller().scrollTop).toBe(800);expect(scroller().dataset.newMessages).toBe('0');expect(seen).toHaveBeenCalled();
});

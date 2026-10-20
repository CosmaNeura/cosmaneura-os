import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {useMobileChatFrame} from './MobileChatFrame';

let root:Root,host:HTMLDivElement,observers:{callback:()=>void;disconnect:ReturnType<typeof vi.fn>}[];
let height=1000,visible=200;
function Frame({owner,messages='one',current=true,active=true}:{owner:object;messages?:string;current?:boolean;active?:boolean}){
  const frame=useMobileChatFrame({active,owner,scope:'invented-workspace:chief',messages,isCurrent:()=>current});
  return <div ref={frame.scrollRef} onScroll={frame.onScroll}>Invented saved conversation</div>;
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

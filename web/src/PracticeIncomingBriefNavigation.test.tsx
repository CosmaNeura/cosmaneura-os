import {act,useContext,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {PracticeHub} from './PracticeHub';
import {IncomingBriefNavigation} from './incoming-brief-navigation';
import {useUnsavedWork} from './unsaved-work';
import {routineId} from './routine-test-fixture';

vi.mock('./InboxMount',()=>({INBOX_BUILD:true,InboxMount:()=>null}));
vi.mock('./InboxHandoffMount',()=>({INBOX_HANDOFF_BUILD:true,InboxHandoffMount:({selectedTicketId,onBusyChange}:{selectedTicketId?:string;onBusyChange?:(busy:boolean)=>void})=><section aria-label="Mounted handoff"><output>{selectedTicketId}</output><button onClick={()=>onBusyChange?.(true)}>Hold pending handoff</button></section>}));
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented.token.value'};
let root:Root,host:HTMLDivElement,oldOpen:((id:string)=>void)|undefined;
function Draft(){
  const nav=useContext(IncomingBriefNavigation),[text,setText]=useState('');
  useUnsavedWork(text.length>0);oldOpen=nav?.openTicket;
  return <><input aria-label="Unfinished source draft" value={text} onChange={e=>setText(e.target.value)}/>
    <button disabled={nav?.blocked} onClick={()=>nav?.openTicket(routineId(7))}>Open dated incoming target</button></>;
}
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function mount(current=identity){await act(async()=>root.render(<PracticeHub identity={current} onDenied={vi.fn()}><Draft/></PracticeHub>));}
async function click(text:string){await act(async()=>[...host.querySelectorAll('button')].find(x=>x.textContent===text)!.click());}
async function edit(value:string){await act(async()=>{const input=host.querySelector('input')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}

it('opens the exact current catalog target with the assigned view still mounted',async()=>{
  await mount();const input=host.querySelector('input');await click('Open dated incoming target');
  expect(host.querySelector('output')?.textContent).toBe(routineId(7));expect(host.querySelector('input')).toBe(input);
  expect(input?.closest('[hidden]')).not.toBeNull();
});
it('refuses brief navigation while an unsaved draft exists and preserves its text',async()=>{
  await mount();await edit('Keep this unfinished draft');await click('Open dated incoming target');
  expect(host.querySelector('output')).toBeNull();expect(host.querySelector('input')?.value).toBe('Keep this unfinished draft');
  await edit('');await click('Open dated incoming target');expect(host.querySelector('output')?.textContent).toBe(routineId(7));
});
it('refuses a stale identity callback and blocks navigation during a pending handoff',async()=>{
  await mount();const stale=oldOpen!;await mount({...identity});await act(async()=>stale(routineId(8)));
  expect(host.querySelector('output')).toBeNull();await click('Open dated incoming target');await click('Hold pending handoff');
  await act(async()=>oldOpen!(routineId(8)));expect(host.querySelector('output')?.textContent).toBe(routineId(7));
});

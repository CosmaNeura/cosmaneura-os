import {act,useEffect} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {PracticeHub} from './PracticeHub';

const mounted=vi.hoisted(()=>({incoming:vi.fn(),handoffs:vi.fn()}));
vi.mock('./InboxMount',()=>({INBOX_BUILD:true,InboxMount:({onBusyChange}:{onBusyChange?:(busy:boolean)=>void})=>{
 useEffect(()=>{mounted.incoming();},[]);return <section aria-label="Incoming test view"><input aria-label="Retained message review" defaultValue="Invented draft"/><button onClick={()=>onBusyChange?.(true)}>Keep pending review</button><button onClick={()=>onBusyChange?.(false)}>Recover review</button></section>;
}}));
vi.mock('./InboxHandoffMount',()=>({INBOX_HANDOFF_BUILD:true,InboxHandoffMount:()=>{useEffect(()=>{mounted.handoffs();},[]);return <section aria-label="Follow-up test view">Responsibility and saved result</section>;}}));
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
const mount=()=>act(async()=>root.render(<PracticeHub identity={identity} onDenied={vi.fn()}><p>Saved assigned work</p></PracticeHub>));
function button(text:string){return [...host.querySelectorAll('button')].find(item=>!item.closest('[hidden]')&&item.textContent?.includes(text))!;}
const click=(text:string)=>act(async()=>button(text).click());

it('opens incoming work only on a visible user action and retains the same review on return',async()=>{
 await mount();expect(mounted.incoming).not.toHaveBeenCalled();expect(mounted.handoffs).not.toHaveBeenCalled();
 const action=button('Review incoming messages');expect(action.tagName).toBe('BUTTON');action.focus();expect(document.activeElement).toBe(action);
 await click('Review incoming messages');expect(mounted.incoming).toHaveBeenCalledOnce();expect(mounted.handoffs).not.toHaveBeenCalled();
 const input=host.querySelector('input');await click('Assigned to me');expect(input?.closest('[hidden]')).not.toBeNull();
 await click('Review incoming messages');expect(host.querySelector('input')).toBe(input);expect(mounted.incoming).toHaveBeenCalledOnce();
});
it('blocks view changes while recovery is needed then opens follow-up without claiming completion',async()=>{
 await mount();await click('Review incoming messages');await click('Keep pending review');
 expect(button('Assigned to me').disabled).toBe(true);await click('Assigned to me');expect(host.querySelector('[aria-label="Incoming test view"]')?.closest('[hidden]')).toBeNull();
 expect(mounted.handoffs).not.toHaveBeenCalled();await click('Recover review');await click('Assigned to me');await click('Review incoming follow-up');
 expect(mounted.handoffs).toHaveBeenCalledOnce();expect(host.textContent).toContain('Responsibility and saved result');expect(host.textContent).not.toContain('Completed');
});

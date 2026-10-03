import {act,type ComponentType} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {deferredWorkspacePanel} from './DeferredWorkspacePanel';
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
it('does not load before mounting and explicitly retries a failed import',async()=>{
 const load=vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(()=> <p>Review ready</p>);
 const Panel=deferredWorkspacePanel(load,'Review');expect(load).not.toHaveBeenCalled();
 await act(async()=>root.render(<Panel/>));expect(host.textContent).toContain('could not open');expect(load).toHaveBeenCalledOnce();
 await act(async()=>{await Promise.resolve();});expect(load).toHaveBeenCalledOnce();
 await act(async()=>host.querySelector('button')!.click());expect(host.textContent).toContain('Review ready');expect(load).toHaveBeenCalledTimes(2);
 await act(async()=>root.render(<Panel/>));expect(load).toHaveBeenCalledTimes(2);
});
it('uses current account props after delayed code resolution and ignores detached owners',async()=>{
 let finish!:(panel:ComponentType<{account:string}>)=>void;
 const load=vi.fn(()=>new Promise<ComponentType<{account:string}>>(resolve=>{finish=resolve;}));
 const Panel=deferredWorkspacePanel(load,'Practice');
 await act(async()=>root.render(<Panel account="old-owner"/>));expect(host.textContent).toContain('Opening');
 await act(async()=>root.render(<Panel account="current-owner"/>));
 await act(async()=>finish(({account})=><p>{account}</p>));expect(host.textContent).toContain('current-owner');expect(host.textContent).not.toContain('old-owner');
 await act(async()=>root.render(<p>Account exited</p>));expect(host.textContent).toBe('Account exited');expect(load).toHaveBeenCalledOnce();
});
it('shares one code request while independently canceling detached mounts',async()=>{
 let finish!:(panel:ComponentType<{account:string}>)=>void;
 const load=vi.fn(()=>new Promise<ComponentType<{account:string}>>(resolve=>{finish=resolve;}));
 const Panel=deferredWorkspacePanel(load,'Practice');
 await act(async()=>root.render(<><Panel key="one" account="one"/><Panel key="two" account="two"/></>));expect(load).toHaveBeenCalledOnce();
 await act(async()=>root.render(<><Panel key="two" account="two"/></>));
 await act(async()=>finish(({account})=><p>{account}</p>));expect(host.textContent).toBe('two');expect(load).toHaveBeenCalledOnce();
});

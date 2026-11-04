import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CopyAnswer} from './CopyAnswer';

let root:Root,host:HTMLDivElement;
const write=vi.fn(),current=vi.fn(()=>true),scope={};
const content='## Invented visit draft\n\nVerify the documented history.\n';
async function render(extra:Partial<Parameters<typeof CopyAnswer>[0]>={}){await act(async()=>root.render(<CopyAnswer content={content} scope={scope} disabled={false} isCurrent={current} {...extra}/>));}
async function click(label='Copy answer'){await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent===label)!.click());}
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);vi.clearAllMocks();current.mockReturnValue(true);write.mockResolvedValue(undefined);vi.stubGlobal('navigator',{clipboard:{writeText:write}});});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('copies only after an explicit click, retaining the exact completed answer',async()=>{
 await render();expect(write).not.toHaveBeenCalled();await click();expect(write).toHaveBeenCalledExactlyOnceWith(content);expect(host.querySelector('[role=status]')?.textContent).toContain('Copied to your clipboard');expect(host.textContent).toContain('Review the draft before using it');
});
it.each(['denied','absent'])('provides selectable exact text when the clipboard is %s',async reason=>{
 if(reason==='absent')vi.stubGlobal('navigator',{clipboard:undefined});else write.mockRejectedValue(new DOMException('Denied','NotAllowedError'));
 await render();await click();expect(host.querySelector('[role=status]')?.textContent).toContain('Select the answer below');const field=host.querySelector('textarea')!;expect(field.readOnly).toBe(true);expect(field.value).toBe(content);expect(field.selectionStart).toBe(0);await click('Select answer');expect(document.activeElement).toBe(field);expect(field.selectionEnd).toBe(content.length);expect(write).toHaveBeenCalledTimes(reason==='absent'?0:1);
});
it.each(['locked','stale','empty'])('does not dispatch a copy when %s',async gate=>{
 if(gate==='stale')current.mockReturnValue(false);await render({disabled:gate==='locked',content:gate==='empty'?'  ':content});await click();expect(write).not.toHaveBeenCalled();expect(host.querySelector('[role=status]')).toBeNull();
});
it('prevents a second copy while the first explicit request is unresolved',async()=>{
 let finish!:()=>void;write.mockImplementation(()=>new Promise<void>(resolve=>{finish=resolve;}));await render();await click();await click();expect(write).toHaveBeenCalledOnce();expect(host.querySelector('button')!.disabled).toBe(true);await act(async()=>finish());expect(host.querySelector('[role=status]')?.textContent).toContain('Copied');
});
it.each(['scope','content','closed','locked','stale'])('does not show a late clipboard result after the %s changes',async change=>{
 let fail!:(error:Error)=>void;write.mockImplementation(()=>new Promise<void>((_,reject)=>{fail=reject;}));await render();await click();
 if(change==='closed')await act(async()=>root.render(null));else if(change==='stale'){current.mockReturnValue(false);await render();}else await render(change==='scope'?{scope:{}}:change==='content'?{content:'Another invented answer'}:{disabled:true});
 await act(async()=>fail(new Error('Denied')));expect(host.querySelector('textarea')).toBeNull();expect(host.textContent).not.toContain('Select the answer below');
});

it('allows an explicit retry after a temporary lock hides a settled result',async()=>{
 let fail!:(error:Error)=>void;write.mockImplementationOnce(()=>new Promise<void>((_,reject)=>{fail=reject;}));await render();await click();await render({disabled:true});await act(async()=>fail(new Error('Denied')));expect(host.querySelector('[role=status]')).toBeNull();await render();expect(host.querySelector('button')!.disabled).toBe(false);write.mockResolvedValue(undefined);await click();expect(write).toHaveBeenCalledTimes(2);expect(host.querySelector('[role=status]')?.textContent).toContain('Copied to your clipboard');
});

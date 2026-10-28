import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {WorkspaceDialog} from './WorkspaceDialog';

let root:Root,host:HTMLDivElement,origin:HTMLDivElement,trigger:HTMLButtonElement;
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);origin=document.createElement('div');trigger=document.createElement('button');trigger.textContent='Open details';origin.append(trigger);host=document.createElement('div');document.body.append(origin,host);root=createRoot(host);trigger.focus();});
afterEach(async()=>{await act(async()=>root.unmount());origin.remove();host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
async function open(canRestoreFocus?:()=>boolean){await act(async()=>root.render(<WorkspaceDialog title="Details" closeLabel="Close details" onClose={()=>root.render(null)} canRestoreFocus={canRestoreFocus}><button>Last action</button></WorkspaceDialog>));}
async function close(){await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="Close details"]')!.click());}

it('returns to the invoking control without moving its reading position',async()=>{
 origin.scrollTop=213;const focus=trigger.focus.bind(trigger),called=vi.spyOn(trigger,'focus').mockImplementation(options=>{if(!options?.preventScroll)origin.scrollTop=0;focus(options);});await open();await close();
 expect(document.activeElement).toBe(trigger);expect(called).toHaveBeenCalledWith({preventScroll:true});expect(origin.scrollTop).toBe(213);
});

it.each(['hidden','css-hidden','inert','aria-hidden','disabled','disabled-fieldset'] as const)('does not restore focus to a connected %s opener',async reason=>{
 await open();const focus=vi.spyOn(trigger,'focus');if(reason==='hidden')origin.hidden=true;else if(reason==='css-hidden')origin.style.display='none';else if(reason==='inert')origin.setAttribute('inert','');else if(reason==='aria-hidden')origin.setAttribute('aria-hidden','true');else if(reason==='disabled')trigger.disabled=true;else{const fieldset=document.createElement('fieldset');fieldset.disabled=true;origin.append(fieldset);fieldset.append(trigger);}
 await close();expect(focus).not.toHaveBeenCalled();
});

it('rejects an obsolete owner episode even when its visible control is reused by the same named context',async()=>{
 const first={name:'Chief'},second={name:'Follow-up'};let current=first;await open(()=>current===first);const focus=vi.spyOn(trigger,'focus');current=second;current={name:'Chief'};await close();expect(focus).not.toHaveBeenCalled();
});

it('does not steal focus already placed by a newer task',async()=>{
 await open();const destination=document.createElement('button');destination.textContent='New task';origin.append(destination);destination.focus();const focus=vi.spyOn(trigger,'focus');await act(async()=>root.render(null));expect(document.activeElement).toBe(destination);expect(focus).not.toHaveBeenCalled();
});

it('does not briefly refocus an old editor while a replacement dialog mounts',async()=>{
 const editor=document.createElement('textarea');origin.append(editor);editor.focus();await open();const focus=vi.spyOn(editor,'focus');await act(async()=>root.render(<WorkspaceDialog key="replacement" title="New task" closeLabel="Close new task" onClose={()=>{}}><button>New action</button></WorkspaceDialog>));expect(focus).not.toHaveBeenCalled();expect(document.activeElement?.getAttribute('aria-label')).toBe('Close new task');
});

it('preserves legitimate same-context editor restoration and the Escape/Tab trap',async()=>{
 const editor=document.createElement('textarea');editor.value='Keep the exact draft.';origin.append(editor);editor.focus();await open();const focus=vi.spyOn(editor,'focus'),first=host.querySelector<HTMLButtonElement>('[aria-label="Close details"]')!,last=[...host.querySelectorAll<HTMLButtonElement>('button')].at(-1)!;
 last.focus();await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true})));expect(document.activeElement).toBe(first);
 await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true})));expect(document.activeElement).toBe(last);
 await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})));expect(document.activeElement).toBe(editor);expect(editor.value).toBe('Keep the exact draft.');expect(focus).toHaveBeenCalledWith({preventScroll:true});
});

it('retains the opener when a dialog control already received autoFocus before its effect',async()=>{
 await act(async()=>root.render(<WorkspaceDialog title="Edit reference" onClose={()=>root.render(null)}><input autoFocus aria-label="Reference"/><button onClick={()=>root.render(null)}>Done</button></WorkspaceDialog>));expect(document.activeElement?.getAttribute('aria-label')).toBe('Reference');await act(async()=>host.querySelector<HTMLButtonElement>('button')!.click());expect(document.activeElement).toBe(trigger);
});

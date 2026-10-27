import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {ConversationDetails} from './MessagesPresentation';

let root:Root,host:HTMLDivElement,opener:HTMLButtonElement;
const task=vi.fn(),ehr=vi.fn(),google=vi.fn(),close=vi.fn();
const props={name:'Chief',context:'Alex Example · Practice visit',contextKind:'Invented visit',locked:false,onTask:task,onReviewAppointment:ehr,onReviewGoogle:google,onClose:()=>{close();root.render(null);}};
const visible=(element:Element)=>!element.closest('[hidden]');
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(element=>visible(element)&&(element.textContent?.trim()===label||element.getAttribute('aria-label')===label))!;
async function click(label:string){await act(async()=>button(label).click());}
async function open(extra:Partial<Parameters<typeof ConversationDetails>[0]>={}){await act(async()=>root.render(<ConversationDetails {...props} {...extra}/>));}
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();host=document.createElement('div');host.className='team-workspace';opener=document.createElement('button');opener.textContent='Details';document.body.append(opener,host);opener.focus();root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();opener.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('keeps three initial groups with one source entry, then shows only the available choices in the same sheet',async()=>{
 await open();const dialog=host.querySelector<HTMLElement>('[role="dialog"]')!,launcher=host.querySelector('.messages-details');
 expect([...host.querySelectorAll('.messages-details section')].filter(visible).map(section=>section.querySelector('h2')?.textContent)).toEqual(['Review','Notes and sources','Activity']);
 expect([...button('Choose notes or sources').closest('section')!.querySelectorAll('button')].filter(visible)).toHaveLength(1);expect(button('Review EHR records')).toBeUndefined();
 await click('Choose notes or sources');
 expect(host.querySelectorAll('[role="dialog"]')).toHaveLength(1);expect(host.querySelector('[role="dialog"]')).toBe(dialog);expect(host.querySelector('.messages-details')).toBe(launcher);expect(launcher?.closest('[hidden]')).toBeNull();
 expect(document.activeElement).toBe(button('Back to details'));expect(dialog.querySelector('.workspace-dialog-heading h2')?.textContent).toBe('Notes and sources');
 expect(button('Review EHR records')).toBeDefined();expect(button('Review Gmail email')).toBeDefined();expect(button('Review Outlook email')).toBeUndefined();expect(button('Review received fax')).toBeUndefined();
 expect(task).not.toHaveBeenCalled();expect(ehr).not.toHaveBeenCalled();expect(google).not.toHaveBeenCalled();expect(close).not.toHaveBeenCalled();
 await click('Review EHR records');expect(ehr).toHaveBeenCalledOnce();expect(task).not.toHaveBeenCalled();expect(google).not.toHaveBeenCalled();
});

it('returns to the same entry and exact Details reading position without closing or launching work',async()=>{
 await open();const dialog=host.querySelector<HTMLElement>('[role="dialog"]')!,entry=button('Choose notes or sources'),focus=vi.spyOn(entry,'focus');dialog.scrollTop=196;
 await click('Choose notes or sources');expect(dialog.scrollTop).toBe(0);dialog.scrollTop=284;
 await click('Back to details');expect(document.activeElement).toBe(entry);expect(focus).toHaveBeenCalledWith({preventScroll:true});expect(dialog.scrollTop).toBe(196);expect(button('Review EHR records')).toBeUndefined();expect(close).not.toHaveBeenCalled();expect(task).not.toHaveBeenCalled();
});

it('keeps review and linked-work actions direct while local source tasks remain reachable without a connector',async()=>{
 await open({onReviewAppointment:undefined,onReviewGoogle:undefined});await click('Visit note');expect(task).toHaveBeenLastCalledWith('Review');await click('Follow-up and linked work');expect(task).toHaveBeenLastCalledWith('Work');
 await click('Choose notes or sources');expect([...host.querySelectorAll('.messages-source-choices section')].filter(visible)).toHaveLength(1);await click('Saved sources');expect(task).toHaveBeenLastCalledWith('Sources');
 await click('Notebook and recording');expect(task).toHaveBeenLastCalledWith('Notebook');await click('Tools for this conversation');expect(task).toHaveBeenLastCalledWith('Tools');
});

it('honors a navigation lock before and after the source chooser opens',async()=>{
 await open({locked:true});expect(button('Choose notes or sources').disabled).toBe(true);await click('Choose notes or sources');expect(button('Back to details')).toBeUndefined();
 await open();await click('Choose notes or sources');await open({locked:true});expect(button('Review EHR records').disabled).toBe(true);expect(button('Saved sources').disabled).toBe(true);expect(button('Back to details').disabled).toBe(true);await click('Review EHR records');expect(ehr).not.toHaveBeenCalled();
});

it.each(['Escape','Close conversation details'] as const)('dismisses the source chooser through %s and restores the original opener',async dismissal=>{
 await open();await click('Choose notes or sources');if(dismissal==='Escape')await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));else await click(dismissal);
 expect(close).toHaveBeenCalledOnce();expect(host.querySelector('[role="dialog"]')).toBeNull();expect(document.activeElement).toBe(opener);expect(task).not.toHaveBeenCalled();
});

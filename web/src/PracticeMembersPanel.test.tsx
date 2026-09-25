import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {PracticeAccessPanel} from './PracticeAccessPanel';
import {PracticeMembersPanel} from './PracticeMembersPanel';
import {practiceAccessApi} from './practice-access-api';
import {WorkspaceApiError} from './workspace-api';
import {memberPage,memberReceipt,practiceMember as row} from './practice-members-test-fixture';
import type {MembersPage} from './practice-members-contract';
let container:HTMLDivElement,root:Root;
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented.token'},loss=vi.fn(),busy=vi.fn();
const paused:MembersPage={...memberPage,members:[{...row,state:'inactive',action:'reactivate',review_sha256:'b'.repeat(64)}]};
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});container=document.createElement('div');document.body.append(container);root=createRoot(container);loss.mockClear();busy.mockClear();
  vi.spyOn(practiceAccessApi,'pending').mockResolvedValue([]);vi.spyOn(practiceAccessApi,'members').mockResolvedValue(memberPage);
  vi.spyOn(practiceAccessApi,'memberChange').mockImplementation(async(_id,command)=>memberReceipt(command));
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();});
const button=(text:string)=>[...container.querySelectorAll('button')].find(item=>item.textContent===text)!;
async function click(text:string){expect(button(text)).toBeDefined();await act(async()=>button(text).click());}
async function confirm(){await act(async()=>container.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());}
async function standalone(id=identity){await act(async()=>root.render(<PracticeMembersPanel identity={id} onBusyChange={busy} onAccessLost={loss}/>));}
it('opens from existing Practice access and requires a review before pausing',async()=>{
  await act(async()=>root.render(<PracticeAccessPanel identity={identity} access={{role:'owner',onAccessLost:loss}} onBusyChange={busy}/>));
  expect(practiceAccessApi.members).not.toHaveBeenCalled();await click('Manage connected members');await click('Review pause for Ada Beta');
  expect(button('Pause CosmasOS access').disabled).toBe(true);await confirm();vi.mocked(practiceAccessApi.members).mockResolvedValue(paused);await click('Pause CosmasOS access');
  expect(practiceAccessApi.memberChange).toHaveBeenCalledOnce();expect(vi.mocked(practiceAccessApi.memberChange).mock.calls[0][1]).toMatchObject({member_id:row.member_id,action:'deactivate',reviewed_at:row.reviewed_at,review_sha256:row.review_sha256,confirm:true});
  expect(container.textContent).toContain('Access paused');expect(button('Review restore for Ada Beta')).toBeDefined();expect(button('Hide connected members').disabled).toBe(false);
});
it('recovers the same change while showing a later restored state separately',async()=>{
  vi.mocked(practiceAccessApi.memberChange).mockRejectedValueOnce(new WorkspaceApiError(503));
  await act(async()=>root.render(<PracticeAccessPanel identity={identity} access={{role:'owner',onAccessLost:loss}} onBusyChange={busy}/>));
  await click('Manage connected members');await click('Review pause for Ada Beta');await confirm();await click('Pause CosmasOS access');
  expect(button('Hide connected members').disabled).toBe(true);expect(button('Refresh requests').disabled).toBe(true);expect(button('Refresh members').disabled).toBe(true);
  vi.mocked(practiceAccessApi.memberChange).mockImplementation(async(_id,command)=>memberReceipt(command,true));
  vi.mocked(practiceAccessApi.members).mockResolvedValue({...memberPage,members:[{...row,review_sha256:'c'.repeat(64)}]});await click('Recover access change');
  const calls=vi.mocked(practiceAccessApi.memberChange).mock.calls;expect(calls).toHaveLength(2);expect(calls[0][1]).toEqual(calls[1][1]);
  expect(container.textContent).toContain('Previously recorded change recovered: access paused');expect(container.textContent).toContain('Access active');
  expect(button('Review pause for Ada Beta')).toBeDefined();expect(button('Hide connected members').disabled).toBe(false);
});
it('requires a fresh review to restore and clears an expired review without retrying',async()=>{
  vi.mocked(practiceAccessApi.members).mockResolvedValue(paused);await standalone();await click('Review restore for Ada Beta');
  expect(button('Restore CosmasOS access').disabled).toBe(true);await confirm();vi.mocked(practiceAccessApi.memberChange).mockRejectedValueOnce(new WorkspaceApiError(409));await click('Restore CosmasOS access');
  expect(container.textContent).toContain('review expired');expect(container.textContent).not.toContain('Ada Beta');expect(button('Refresh members').disabled).toBe(false);expect(practiceAccessApi.memberChange).toHaveBeenCalledOnce();
});
it('keeps the current owner read-only and clears a roster after authority loss',async()=>{
  vi.mocked(practiceAccessApi.members).mockResolvedValue({...memberPage,members:[{...row,role:'owner',action:null}]});await standalone();
  expect(container.textContent).toContain('Practice owner');expect(button('Review pause for Ada Beta')).toBeUndefined();
  vi.mocked(practiceAccessApi.members).mockRejectedValueOnce(new WorkspaceApiError(403));await click('Refresh members');expect(loss).toHaveBeenCalledOnce();expect(container.textContent).not.toContain('Ada Beta');
});
it('discards a late private roster when the account changes',async()=>{
  let finish!:(value:MembersPage)=>void;vi.mocked(practiceAccessApi.members).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValueOnce({...memberPage,members:[]});
  await standalone();await standalone({...identity});await act(async()=>finish(memberPage));expect(container.textContent).not.toContain('Ada Beta');
});
it('requests the exact next page and permits a fresh return to the first page',async()=>{
  const rows=Array.from({length:100},(_,index)=>({...row,member_id:`00000000-0000-4000-8000-${String(index+1).padStart(12,'0')}`,display_name:`Member ${index+1}`}));
  const next=rows.at(-1)!.member_id;
  vi.mocked(practiceAccessApi.members).mockResolvedValueOnce({...memberPage,members:rows,next_after_id:next}).mockResolvedValueOnce({...memberPage,members:[]});
  await standalone();await click('Next members');expect(vi.mocked(practiceAccessApi.members).mock.calls[1][1]).toBe(next);
  await click('First member page');expect(vi.mocked(practiceAccessApi.members).mock.calls[2][1]).toBe(null);
});

import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {openDraftStore} from './draft-store';
import {DraftJournal,accountEditorAddress} from './draft-journal';
import {AccountRecoveryContext,type AccountRecoveryAccess} from './account-recovery';
import {PracticeInvitationPanel} from './PracticeInvitationPanel';
import {practiceAccessApi} from './practice-access-api';
import {WorkspaceApiError} from './workspace-api';
import {invitationFromHash,validateInvitation,validateInvitationRecovery,type PracticeInvitation} from './practice-invitation-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const row:PracticeInvitation={invitation_id:'00000000-0000-4000-8000-000000000002',label:'Invented teammate',created_at:'2026-10-16T12:00:00+00:00',expires_at:'2099-01-01T12:00:00+00:00',state:'active',requests:0};
const identity={mode:'clerk_jwt' as const,getToken:vi.fn()},denied=vi.fn();
let host:HTMLDivElement,root:Root,recovery:AccountRecoveryAccess;
beforeEach(async()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  recovery={journal:new DraftJournal(await openDraftStore({scope:'d'.repeat(64),native:false,indexedDB:new IDBFactory(),crypto:webcrypto})),authorize:vi.fn().mockResolvedValue(undefined)};
  vi.spyOn(practiceAccessApi,'invitations').mockResolvedValue([]);host=document.createElement('div');document.body.append(host);root=createRoot(host);denied.mockClear();
});
afterEach(async()=>{await act(async()=>root.unmount());recovery.journal.close();host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
const button=(text:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent===text)!;
async function wait(check:()=>boolean){for(let n=0;n<100&&!check();n++)await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});expect(check(),host.innerHTML).toBe(true);}
async function mount(){await act(async()=>root.render(<AccountRecoveryContext.Provider value={recovery}><PracticeInvitationPanel identity={identity} onBusyChange={()=>{}} onAccessLost={denied}/></AccountRecoveryContext.Provider>));await wait(()=>!!button('Create invitation link')&&!button('Create invitation link').closest('form')!.querySelector('input')!.disabled||!!button('Check invitation result'));}
async function label(){const input=host.querySelector('input')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'Invented teammate');input.dispatchEvent(new Event('input',{bubbles:true}));});}
it('retains the exact encrypted invitation before dispatch and resolves a lost response after remount',async()=>{
  const create=vi.spyOn(practiceAccessApi,'createInvitation').mockImplementation(async(_,body)=>{expect(await recovery.journal.load(accountEditorAddress('practice-invite'))).toMatchObject({pending:body.idempotency_key,data:{pending:{type:'create',body:{idempotency_key:body.idempotency_key,invitation_secret:body.token}}}});throw new WorkspaceApiError(503);});
  await mount();await label();await act(async()=>button('Create invitation link').click());await wait(()=>!!button('Check invitation result'));
  const body=create.mock.calls[0][1];expect(body.token).toMatch(/^[a-f0-9]{64}$/);
  const savedRow={...row,created_at:new Date(Date.now()).toISOString().replace('Z','+00:00'),expires_at:new Date(Date.now()+72*3600000).toISOString().replace('Z','+00:00')};
  vi.spyOn(practiceAccessApi,'resolveInvitation').mockResolvedValue({outcome:'recorded',invitation:savedRow});
  await act(async()=>root.unmount());root=createRoot(host);await mount();await act(async()=>button('Check invitation result').click());await wait(()=>host.textContent!.includes('Invitation ready to copy.'));
  expect(create).toHaveBeenCalledOnce();expect(practiceAccessApi.resolveInvitation).toHaveBeenCalledExactlyOnceWith(identity,{type:'create',body});
  expect([...host.querySelectorAll<HTMLInputElement>('input')].find(input=>input.readOnly)?.value).toContain(`#cosmas/invite/${body.token}`);
  expect(await recovery.journal.load(accountEditorAddress('practice-invite'))).toMatchObject({pending:null,data:{confirmed:{invitation_secret:body.token}}});
});
it('checks absence before allowing an explicit retry with the same token and key',async()=>{
  const create=vi.spyOn(practiceAccessApi,'createInvitation').mockRejectedValueOnce(new WorkspaceApiError(503));
  vi.spyOn(practiceAccessApi,'resolveInvitation').mockResolvedValue({outcome:'not_found',invitation:null});
  await mount();await label();await act(async()=>button('Create invitation link').click());await wait(()=>!!button('Check invitation result'));const body=create.mock.calls[0][1];
  await act(async()=>button('Check invitation result').click());expect(create).toHaveBeenCalledOnce();create.mockResolvedValue({...row,created_at:'2026-10-16T12:00:00+00:00',expires_at:'2026-10-19T12:00:00+00:00'});
  await act(async()=>button('Retry same invitation request').click());await wait(()=>host.textContent!.includes('Invitation ready to copy.'));expect(create.mock.calls[1]).toEqual([identity,body]);
});
it('rejects unbounded or malformed invitation and recovery metadata',()=>{
  expect(invitationFromHash(`#cosmas/invite/${'a'.repeat(64)}`)).toBe('a'.repeat(64));expect(invitationFromHash('#cosmas/invite/identity-matching-code')).toBeNull();
  expect(()=>validateInvitation(row)).toThrow();expect(()=>validateInvitationRecovery({contract:'practice-invitation-recovery.v1',pending:null,confirmed:{invitation:row,token:'matching-code'}})).toThrow();
});

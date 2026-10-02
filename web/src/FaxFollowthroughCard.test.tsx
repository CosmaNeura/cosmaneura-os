import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {FaxFollowthroughCard} from './FaxFollowthroughCard';
import {readFaxStatus,type FaxStatus} from './fax-status-api';
import {faxFixture,faxScope,faxTicket} from './fax-status-test-fixture';
vi.mock('./fax-status-api',()=>({readFaxStatus:vi.fn()}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented'};
describe('compact saved fax receipts and human next action',()=>{
  let root:Root,container:HTMLDivElement;
  beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();container=document.createElement('div');document.body.append(container);root=createRoot(container);});
  afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.unstubAllGlobals();});
  const render=async(current=identity)=>{await act(async()=>root.render(<FaxFollowthroughCard identity={current} workspaceId={faxScope.workspace_id} ticketId={faxTicket} version={1} head={'a'.repeat(64)}/>));};
  it('keeps posting and human verification distinct from delivery and missing counts',async()=>{
    vi.mocked(readFaxStatus).mockResolvedValue(await faxFixture({provider:'spruce',status_label:'Posted in Spruce; fax delivery unconfirmed',external_outcome:'spruce_posted_delivery_unconfirmed',next_step:{code:'verify_in_spruce',label:'Verify fax delivery in Spruce',requires_human:true}}));await render();
    expect(container.textContent).toContain('delivery unconfirmed');expect(container.textContent).toContain('Human completion review remains separate');expect(container.textContent).toContain('do not assume zero');expect(container.querySelectorAll('button')).toHaveLength(1);
  });
  it('retains the accessible retry button and focus while only repeating the saved GET',async()=>{
    vi.mocked(readFaxStatus).mockRejectedValueOnce(new Error('lost local read')).mockResolvedValueOnce(await faxFixture());await render();
    const retry=container.querySelector('button')!;expect(retry.textContent).toBe('Retry saved status');retry.focus();await act(async()=>retry.click());
    expect(readFaxStatus).toHaveBeenCalledTimes(2);expect(document.activeElement).toBe(retry);expect(container.querySelector('button')).toBe(retry);expect(retry.textContent).toBe('Refresh saved status');
  });
  it('withholds old owner results and discards a late response after owner change',async()=>{
    let finish!:(value:FaxStatus)=>void;vi.mocked(readFaxStatus).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValueOnce(await faxFixture({source_current:false,status_label:'New owner current saved work'}));await render();
    const signal=vi.mocked(readFaxStatus).mock.calls[0][3]!;await render({...identity,getToken:async()=>'different'});expect(signal.aborted).toBe(true);
    await act(async()=>finish(await faxFixture({status_label:'OLD OWNER RECEIPT'})));expect(container.textContent).not.toContain('OLD OWNER');expect(container.textContent).toContain('current reviewed source needs checking');
  });
  it('shows partial transmitted pages and recorded observation without claiming human completion',async()=>{
    const observed={id:faxTicket,sequence:1,sha256:'a'.repeat(64),observed_at:'2026-10-02T12:00:00.000000Z',recorded_at:'2026-10-02T12:00:00.000000Z'};
    vi.mocked(readFaxStatus).mockResolvedValue(await faxFixture({transport:'failed',status_label:'Fax transport failed; review the outcome',external_outcome:'provider_transport_failed',observation_head:{sequence:1,sha256:'b'.repeat(64)},last_recorded:observed,pages:{observation:observed,total:3,delivered:1}}));await render();
    expect(container.textContent).toContain('Reported pages: 1 of 3');expect(container.textContent).toContain('Last recorded provider observation');expect(container.textContent).not.toContain('Local human outcome verified.');
  });
});

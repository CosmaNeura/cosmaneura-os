import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {parseFaxStatus,readFaxStatus} from './fax-status-api';
import {faxFixture,faxScope,faxTicket} from './fax-status-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
describe('closed receipt-bound saved fax GET',()=>{
  beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');});
  afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();});
  it('does one signed no-store GET and binds the selected saved work',async()=>{
    const value=await faxFixture(),fetcher=vi.fn(async()=>new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
    expect(await readFaxStatus({mode:'clerk_jwt',getToken:async()=>'invented-token'},faxScope.workspace_id,faxTicket)).toEqual(value);
    expect(fetcher).toHaveBeenCalledTimes(1);const [url,options]=fetcher.mock.calls[0] as unknown as [string,RequestInit];
    expect(url).toBe(`http://127.0.0.1:8000/workspaces/${faxScope.workspace_id}/vendor-work/${faxTicket}/status`);
    expect(options.method).toBe('GET');expect(options.cache).toBe('no-store');expect(options.body).toBeUndefined();
  });
  it('refuses altered or extra material and unsupported delivery implications',async()=>{
    const value=await faxFixture();await expect(parseFaxStatus({...value,status_label:'Altered'})).rejects.toThrow();
    await expect(parseFaxStatus({...value,provider_response:'forbidden'})).rejects.toThrow();
    await expect(parseFaxStatus(await faxFixture({provider:'spruce',transport:'delivered',external_outcome:'provider_transport_delivered'}))).rejects.toThrow();
    await expect(parseFaxStatus(await faxFixture({observation_head:{sequence:1,sha256:'b'.repeat(64)}}))).rejects.toThrow();
  });
  it('refuses wrong selected scope even with a valid commitment and never retries',async()=>{
    const value=await faxFixture({ticket_id:'77777777-7777-4777-8777-777777777777'}),fetcher=vi.fn(async()=>new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
    await expect(readFaxStatus({boxId:faxScope.box_id,actorId:faxScope.owner_id},faxScope.workspace_id,faxTicket)).rejects.toThrow();expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('bounds untrusted response bytes without an automatic retry',async()=>{
    const fetcher=vi.fn(async()=>new Response(' '.repeat(8193),{status:200,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
    await expect(readFaxStatus({mode:'clerk_jwt',getToken:async()=>'invented'},faxScope.workspace_id,faxTicket)).rejects.toThrow();expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

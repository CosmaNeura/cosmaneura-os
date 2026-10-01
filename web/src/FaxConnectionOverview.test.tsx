import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {FaxConnectionOverview} from './FaxConnectionOverview';
import type {FaxReadiness} from './fax-readiness-api';

const ready:FaxReadiness={contract_version:1,scope:{box_id:'00000000-0000-4000-8000-000000000001',owner_id:'00000000-0000-4000-8000-000000000002'},enabled:true,work_enabled:true,delivery_enabled:true,credential_access_configured:true,document_storage_configured:true,
  providers:[{id:'spruce',installed_accounts:0,active_accounts:0,review_required_accounts:0,unavailable_accounts:0,prepare_enabled_accounts:0},
    {id:'srfax',installed_accounts:1,active_accounts:1,review_required_accounts:0,unavailable_accounts:0,prepare_enabled_accounts:1},
    {id:'documo',installed_accounts:1,active_accounts:0,review_required_accounts:1,unavailable_accounts:0,prepare_enabled_accounts:0},
    {id:'efax',installed_accounts:0,active_accounts:0,review_required_accounts:0,unavailable_accounts:0,prepare_enabled_accounts:0}]};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
const button=(text:string)=>[...host.querySelectorAll('button')].find(item=>item.textContent===text)!;
it('shows provider choices and routes only after an explicit work click',async()=>{
  const work=vi.fn(),setup=vi.fn();await act(async()=>root.render(<FaxConnectionOverview value={ready} loading={false} unavailable={false} locked={false} onRefresh={vi.fn()} onSetup={setup} onOpenWork={work} workLabel="Open fax work" workBlocked={false}/>));
  expect(work).not.toHaveBeenCalled();expect(host.textContent).toContain('Spruce');expect(host.textContent).toContain('SRFax');expect(host.textContent).toContain('Documo');expect(host.textContent).toContain('Account needs review');
  expect(host.textContent).toContain('eFax Corporate');expect(host.textContent).toContain('may not include API access');expect(host.textContent).not.toContain('Delivery verified');
  await act(async()=>button('Open fax work').click());expect(work).toHaveBeenCalledOnce();expect(setup).not.toHaveBeenCalled();
  await act(async()=>button('Review provider accounts').click());expect(setup).toHaveBeenCalledOnce();
});
it.each([{loading:true,unavailable:false,locked:false,workBlocked:false},{loading:false,unavailable:true,locked:false,workBlocked:false},{loading:false,unavailable:false,locked:true,workBlocked:false},{loading:false,unavailable:false,locked:false,workBlocked:true}])('does not navigate from stale or locked readiness %j',async flags=>{
  const work=vi.fn();await act(async()=>root.render(<FaxConnectionOverview value={ready} {...flags} onRefresh={vi.fn()} onSetup={vi.fn()} onOpenWork={work} workLabel="Open fax work"/>));
  expect(button('Open fax work').disabled).toBe(true);await act(async()=>button('Open fax work').click());expect(work).not.toHaveBeenCalled();
});
it('gives concrete missing prerequisites without offering a fake connection or send',async()=>{
  await act(async()=>root.render(<FaxConnectionOverview value={{...ready,work_enabled:false,delivery_enabled:false,credential_access_configured:false,document_storage_configured:false,providers:ready.providers.map(row=>({...row,prepare_enabled_accounts:0}))}} loading={false} unavailable={false} locked={false} onRefresh={vi.fn()} onSetup={vi.fn()} onOpenWork={vi.fn()} workLabel="Open fax work" workBlocked={false}/>));
  expect(button('Open fax work').disabled).toBe(true);expect(host.textContent).toContain('private document storage');expect(host.textContent).toContain('secure access');expect(host.textContent).toContain('Enable sending');
  expect([...host.querySelectorAll('button')].some(item=>/send|connect efax/i.test(item.textContent??''))).toBe(false);
});

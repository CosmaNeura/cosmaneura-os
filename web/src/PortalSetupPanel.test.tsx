import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {PortalSetupPanel} from './PortalSetupPanel';
import {portalSetupApi} from './portal-setup-api';
import {actualPortalCatalog,actualPortalProposal,portalFixture,portalReceipt} from './portal-setup-test-fixture';
import {emptyPortalDraft,emptyPortalRecovery,type PortalRecoveryAccess,type PortalRecoveryRecord} from './portal-setup-recovery';
import {preparePortalOperation,verifyPortalDetail,verifyPortalReceipt,type PortalCatalog,type PortalOperation,type PortalProposal,type PortalReceipt} from './portal-setup-contract';
import {vendorDigest} from './vendor-contract';
import {WorkspaceApiError} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-test-token'};
function recovery(initial:PortalRecoveryRecord|null=null){let saved=initial;const access:PortalRecoveryAccess={load:vi.fn(async()=>saved),persist:vi.fn(async value=>{saved=structuredClone(value);}),authorize:vi.fn(async()=>{}),denied:vi.fn()};return {access,value:()=>saved};}
describe('reviewed portal setup with encrypted journal access',()=>{
  let root:Root,container:HTMLDivElement,catalog:PortalCatalog;
  beforeEach(async()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);catalog=await actualPortalCatalog();container=document.createElement('div');document.body.append(container);root=createRoot(container);
    vi.spyOn(portalSetupApi,'catalog').mockImplementation(async()=>structuredClone(catalog));vi.spyOn(portalSetupApi,'command').mockImplementation(async(_i,op)=>portalReceipt(op));vi.spyOn(portalSetupApi,'resolve').mockResolvedValue(await verifyPortalReceipt(portalFixture.proposal_receipt));vi.spyOn(portalSetupApi,'history').mockResolvedValue([]);
  });
  afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
  const button=(label:string)=>Array.from(container.querySelectorAll('button')).find(b=>b.textContent===label)!;
  const waitUi=async(check:()=>void)=>{for(let i=0;i<200;i++){let passed=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();passed=true;}catch{/* Wait for the actual UI state. */}});if(passed)return;}check();};
  const click=async(label:string)=>{await waitUi(()=>{expect(button(label)).toBeTruthy();expect(button(label).matches(':disabled')).toBe(false);});await act(async()=>button(label).click());};
  const render=async(access:PortalRecoveryAccess|null)=>{await act(async()=>root.render(<PortalSetupPanel identity={identity} recovery={access}/>));await waitUi(()=>expect(container.textContent).not.toContain('Loading portal setup'));if(access)await waitUi(()=>expect(access.load).toHaveBeenCalled());};
  const selectCurrent=async()=>{const label=catalog.connections[0].review.profile_label+' · '+catalog.connections[0].review.mappings.patient_label+' · Awaiting your review';await click(label);await waitUi(()=>expect(container.querySelector('[aria-label="Portal mapping review"]')).not.toBeNull());};
  const checks=async()=>{const field=Array.from(container.querySelectorAll('fieldset')).find(f=>f.querySelector('legend')?.textContent==='Review before activation')!;await act(async()=>field.querySelectorAll<HTMLInputElement>('input[type=checkbox]').forEach(i=>i.click()));};
  it('shows production account review and requires its explicit activation confirmation',async()=>{
    catalog.live_portals_configured=true;
    Object.assign(catalog.profiles[0],{portal_id:'example_portal',mode:'production'});
    const detail=catalog.connections[0];Object.assign(detail.review,{portal_id:'example_portal',mode:'production'});
    detail.review_sha256=await vendorDigest('cosmas-portal-setup-review.v1',detail.review);
    detail.last_receipt.effect!.review_sha256=detail.review_sha256;
    const {receipt_sha256:_,...receipt}=detail.last_receipt;
    detail.last_receipt.receipt_sha256=await vendorDigest('cosmas-portal-setup-receipt.v1',receipt);
    await verifyPortalDetail(detail);
    await render(recovery().access);await selectCurrent();
    expect(container.textContent).toContain('Production provider account');
    expect(container.textContent).toContain('I confirm activation for this production provider account');
    expect(container.textContent).not.toContain('I confirm activation for local synthetic testing');
    expect(button('Activate reviewed configuration').matches(':disabled')).toBe(true);
    expect(portalSetupApi.command).not.toHaveBeenCalled();await checks();await click('Activate reviewed configuration');
    await waitUi(()=>expect(portalSetupApi.command).toHaveBeenCalledOnce());
    const operation=vi.mocked(portalSetupApi.command).mock.calls[0][1];
    expect(operation.kind).toBe('activate');expect(operation.request).toMatchObject({review_sha256:detail.review_sha256,confirm_local_activation:true});
  });
  it('shows an unsupported portal as unconfigured with no generic endpoint or credential entry',async()=>{
    catalog={...catalog,profiles:[],connections:[]};await render(recovery().access);expect(container.textContent).toContain('No portal is configured');expect(container.querySelector('input')).toBeNull();expect(portalSetupApi.command).not.toHaveBeenCalled();
  });
  it('requires encrypted recovery before setup changes',async()=>{
    await render(null);expect(container.textContent).toContain('Private encrypted recovery must be available');expect(button('Save mappings for review').matches(':disabled')).toBe(true);expect(portalSetupApi.command).not.toHaveBeenCalled();
  });
  it('restores a saved operation and checks its exact receipt without automatic command or resolution',async()=>{
    const op=await actualPortalProposal(),store=recovery({...emptyPortalRecovery(op.scope),pending:op});await render(store.access);
    expect(portalSetupApi.command).not.toHaveBeenCalled();expect(portalSetupApi.resolve).not.toHaveBeenCalled();await click('Restore portal setup draft');
    expect(portalSetupApi.resolve).not.toHaveBeenCalled();await click('Check saved action');await waitUi(()=>expect(store.value()?.receipt?.outcome).toBe('recorded'));
    expect(portalSetupApi.resolve).toHaveBeenCalledWith(identity,op);expect(portalSetupApi.command).not.toHaveBeenCalled();
    await click('Continue setup');await waitUi(()=>expect(store.value()?.pending).toBeNull());expect(button('Activate reviewed configuration').disabled).toBe(true);
  });
  it('only explicitly retries the exact saved operation after a not-found resolution',async()=>{
    const op=await actualPortalProposal(),store=recovery({...emptyPortalRecovery(op.scope),pending:op});vi.mocked(portalSetupApi.resolve).mockResolvedValue({contract_version:1,outcome:'not_found',scope:op.scope,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
    await render(store.access);await click('Restore portal setup draft');await click('Check saved action');await waitUi(()=>expect(button('Submit exact saved action')).toBeTruthy());expect(portalSetupApi.command).not.toHaveBeenCalled();
    await click('Submit exact saved action');await waitUi(()=>expect(portalSetupApi.command).toHaveBeenCalledWith(identity,op));
  });
  it('serializes rapid field changes locally without authorization or HTTP reads on typing',async()=>{
    const store=recovery();await render(store.access);await selectCurrent();const count=vi.mocked(store.access.authorize).mock.calls.length;const reads=vi.mocked(portalSetupApi.catalog).mock.calls.length;
    const input=(label:string)=>Array.from(container.querySelectorAll('label')).find(l=>l.textContent===label)!.querySelector('input')!;
    const practice=input('Practice label'),recipient=input('Recipient label');
    await act(async()=>{for(const [element,value] of [[practice,'New'],[recipient,'Other'],[practice,'New practice'],[recipient,'Other recipient']] as const){Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(element,value);element.dispatchEvent(new Event('input',{bubbles:true}));}});
    await waitUi(()=>expect(store.value()?.draft).toMatchObject({practice_label:'New practice',recipient_label:'Other recipient'}));expect(store.access.authorize).toHaveBeenCalledTimes(count);expect(portalSetupApi.catalog).toHaveBeenCalledTimes(reads);expect(portalSetupApi.command).not.toHaveBeenCalled();
  });
  it('persists the exact operation before activation and requires all five fresh confirmations',async()=>{
    const store=recovery();await render(store.access);await selectCurrent();expect(button('Activate reviewed configuration').disabled).toBe(true);await checks();
    vi.mocked(portalSetupApi.command).mockImplementation(async(_i,op)=>{expect(store.value()?.pending).toEqual(op);return portalReceipt(op);});
    await click('Activate reviewed configuration');await waitUi(()=>expect(store.value()?.receipt?.outcome).toBe('recorded'));
    const op=vi.mocked(portalSetupApi.command).mock.calls[0][1];expect(op.kind).toBe('activate');expect(op.request).toMatchObject({review_sha256:catalog.connections[0].review_sha256,reviewed_profile:true,reviewed_patient:true,confirm_local_activation:true});
  });
  it('refuses activation after a mapping edit until a new proposal is saved and freshly reviewed',async()=>{
    const store=recovery();await render(store.access);await selectCurrent();await checks();
    const previous=structuredClone(catalog.connections[0]);
    expect(button('Activate reviewed configuration').matches(':disabled')).toBe(false);
    const input=Array.from(container.querySelectorAll('label')).find(l=>l.textContent==='Portal recipient ID')!.querySelector('input')!;
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'recipient_changed');input.dispatchEvent(new Event('input',{bubbles:true}));});
    await waitUi(()=>expect(store.value()?.draft.recipient_reference).toBe('recipient_changed'));
    const activationChecks=()=>Array.from(container.querySelector('[aria-label="Portal mapping review"]')!.querySelectorAll<HTMLInputElement>('fieldset:first-of-type input[type=checkbox]'));
    expect(activationChecks()).toHaveLength(5);
    expect(activationChecks().every(i=>!i.checked)).toBe(true);
    expect(button('Activate reviewed configuration').matches(':disabled')).toBe(true);
    expect(container.textContent).toContain('Save your changed mappings for review before activating this configuration.');
    await act(async()=>button('Activate reviewed configuration').click());
    await checks();
    expect(activationChecks().every(i=>!i.checked)).toBe(true);
    expect(portalSetupApi.command).not.toHaveBeenCalled();
    vi.mocked(portalSetupApi.command).mockImplementation(async(_i,op)=>{
      expect(store.value()?.pending).toEqual(op);
      if(op.kind!=='propose')return portalReceipt(op);
      const request=op.request as PortalProposal;
      const next=structuredClone(previous);
      next.version=request.expected_version+1;next.revision++;next.revision_id=crypto.randomUUID();
      next.review.capabilities=request.capabilities;
      next.review.mappings={...request.mappings,patient_label:previous.review.mappings.patient_label};
      next.review.mappings_sha256=await vendorDigest('cosmas-portal-setup-mappings.v1',{scope:op.scope,installation_id:next.review.installation_id,profile_sha256:next.review.profile_sha256,configuration_sha256:next.review.configuration_sha256,ids:next.review.mapping_ids,mappings:request.mappings});
      next.review_sha256=await vendorDigest('cosmas-portal-setup-review.v1',next.review);
      const receipt=await portalReceipt(op);
      if(!receipt.effect)throw Error('Expected recorded proposal');
      receipt.effect={...receipt.effect,revision_id:next.revision_id,review_sha256:next.review_sha256};
      const {receipt_sha256:_,...body}=receipt;receipt.receipt_sha256=await vendorDigest('cosmas-portal-setup-receipt.v1',body);
      next.last_receipt=await verifyPortalReceipt(receipt,op);
      catalog={...catalog,connections:[await verifyPortalDetail(next)]};
      return next.last_receipt;
    });
    await click('Save mappings for review');await waitUi(()=>expect(store.value()?.receipt?.outcome).toBe('recorded'));
    const proposal=structuredClone(store.value()!.pending!);
    expect(proposal.kind).toBe('propose');expect(proposal.request).toMatchObject({mappings:{recipient_reference:'recipient_changed'}});
    expect(portalSetupApi.command).toHaveBeenCalledTimes(1);
    await click('Continue setup');await waitUi(()=>expect(store.value()?.pending).toBeNull());
    expect(activationChecks().every(i=>!i.checked)).toBe(true);
    expect(button('Activate reviewed configuration').matches(':disabled')).toBe(true);
    expect(catalog.connections[0].review_sha256).not.toBe(previous.review_sha256);
    await checks();await click('Activate reviewed configuration');await waitUi(()=>expect(store.value()?.receipt?.outcome).toBe('recorded'));
    const activated=vi.mocked(portalSetupApi.command).mock.calls[1][1];
    expect(activated.kind).toBe('activate');expect(activated.request).toMatchObject({expected_version:catalog.connections[0].version,revision_id:catalog.connections[0].revision_id,review_sha256:catalog.connections[0].review_sha256});
    expect(store.value()?.pending).toEqual(activated);
    expect(vi.mocked(store.access.persist).mock.calls.some(([saved])=>saved?.pending?.request_sha256===proposal.request_sha256&&saved.receipt?.outcome==='recorded')).toBe(true);
  });
  it('retains and explicitly retries an already journaled activation exactly even when its restored draft differs',async()=>{
    const detail=catalog.connections[0],scope=catalog.scope;
    const original=await preparePortalOperation(scope,'activate',{connection_id:detail.connection_id,expected_version:detail.version,idempotency_key:'saved-portal-activation',revision_id:detail.revision_id,review_sha256:detail.review_sha256,reviewed_profile:true,reviewed_practice:true,reviewed_patient:true,reviewed_recipient:true,confirm_local_activation:true});
    const draft={...emptyPortalDraft(),...portalFixture.proposal.mappings,installation_id:detail.review.installation_id,connection_id:detail.connection_id,expected_version:detail.version,capabilities:detail.review.capabilities,recipient_reference:'different_saved_draft'};
    const store=recovery({...emptyPortalRecovery(scope),draft,selected_connection_id:detail.connection_id,pending:original});
    vi.mocked(portalSetupApi.resolve).mockResolvedValue({contract_version:1,outcome:'not_found',scope,command_kind:original.kind,idempotency_key:original.request.idempotency_key,request_sha256:original.request_sha256});
    await render(store.access);await click('Restore portal setup draft');
    expect(portalSetupApi.command).not.toHaveBeenCalled();expect(portalSetupApi.resolve).not.toHaveBeenCalled();
    await waitUi(()=>expect(button('Activate reviewed configuration').matches(':disabled')).toBe(true));
    await click('Check saved action');await waitUi(()=>expect(store.value()?.receipt?.outcome).toBe('not_found'));
    expect(store.value()?.pending).toEqual(original);expect(store.value()?.draft).toEqual(draft);
    await click('Submit exact saved action');await waitUi(()=>expect(store.value()?.receipt?.outcome).toBe('recorded'));
    expect(portalSetupApi.command).toHaveBeenCalledTimes(1);expect(portalSetupApi.command).toHaveBeenCalledWith(identity,original);
    expect(store.value()?.pending).toEqual(original);expect(store.value()?.draft).toEqual(draft);
  });
  it('does not submit when local persistence fails and reports that no action was sent',async()=>{
    const store=recovery();await render(store.access);await selectCurrent();await checks();vi.mocked(store.access.persist).mockRejectedValueOnce(new Error('local CAS conflict'));
    await click('Activate reviewed configuration');await waitUi(()=>expect(container.textContent).toContain('The setup action was not sent'));expect(portalSetupApi.command).not.toHaveBeenCalled();
  });
  it.each([401,403,404])('immediately hides private mappings and history when authority is denied with %s',async status=>{
    const store=recovery();await render(store.access);await selectCurrent();vi.mocked(portalSetupApi.history).mockRejectedValueOnce(new WorkspaceApiError(status));await click('View saved history');await waitUi(()=>expect(container.textContent).toContain('Access to private portal setup is unavailable'));
    expect(container.textContent).not.toContain(catalog.connections[0].review.mappings.patient_label);expect(container.querySelector('[aria-label="Portal mapping review"]')).toBeNull();expect(store.access.denied).toHaveBeenCalled();
  });
  it('fences a delayed committed response after identity and journal scope change',async()=>{
    const store=recovery();await render(store.access);await selectCurrent();await checks();let release!:(value:PortalReceipt)=>void;let operation!:PortalOperation;
    vi.mocked(portalSetupApi.command).mockImplementationOnce(async(_i,op)=>{operation=op;return new Promise(r=>{release=r;});});await click('Activate reviewed configuration');await waitUi(()=>expect(release).toBeTruthy());
    const next=recovery();catalog={...catalog,connections:[],profiles:[]};await act(async()=>root.render(<PortalSetupPanel identity={{...identity}} recovery={next.access}/>));await waitUi(()=>expect(next.access.load).toHaveBeenCalled());await act(async()=>release(await portalReceipt(operation)));
    expect(next.access.persist).not.toHaveBeenCalled();expect(store.value()?.receipt).toBeNull();expect(container.textContent).toContain('No portal is configured');
  });
});

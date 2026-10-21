import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {mountCreatorReview} from '../../clients/scribe-review/creator-review-panel';
import type {CreatorReviewApi,CreatorReviewView} from '../../clients/scribe-review/creator-review-api';

const view:CreatorReviewView={schema_version:'1.0',session_id:'00000000-0000-4000-8000-000000000001',status:'processing',source:null,working:null,review_queue:null,translation_progress:[]};
let host:HTMLDivElement,dispose:(()=>void)|undefined;
beforeEach(()=>{host=document.createElement('div');document.body.append(host);});
afterEach(()=>{dispose?.();dispose=undefined;host.remove();});
const refresh=()=>host.querySelector<HTMLButtonElement>('[data-review-action="refresh"]')!.click();

it('reports unavailable after a failed read and ready only after an explicit successful refresh',async()=>{
  const availability=vi.fn();let reject!:(cause:unknown)=>void;
  const api:CreatorReviewApi={read:vi.fn().mockImplementationOnce(()=>new Promise((_resolve,no)=>reject=no)).mockResolvedValue(view),decide:vi.fn()};
  dispose=mountCreatorReview(host,api,{onAvailability:availability});
  expect(availability.mock.calls).toEqual([['loading']]);
  reject(new Error('private vendor/session detail'));
  await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(host.textContent).toContain('The transcript could not be retrieved. Choose Refresh to check again.');expect(host.textContent).not.toContain('private vendor/session detail');
  refresh();expect(availability).toHaveBeenLastCalledWith('loading');
  await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('ready'));
  expect(availability.mock.calls).toEqual([['loading'],['unavailable'],['loading'],['ready']]);expect(api.decide).not.toHaveBeenCalled();
});

it('withholds ready until recovery metadata is confirmed and reports a failed journal without its detail',async()=>{
  const availability=vi.fn();let reject!:(cause:unknown)=>void;
  const load=vi.fn(()=>new Promise<null>((_resolve,no)=>reject=no));
  dispose=mountCreatorReview(host,{read:vi.fn().mockResolvedValue(view),decide:vi.fn()},
    {onAvailability:availability,journal:{load,save:vi.fn(),clear:vi.fn()}});
  await vi.waitFor(()=>expect(load).toHaveBeenCalledOnce());expect(availability.mock.calls).toEqual([['loading']]);
  reject(new Error('private encrypted metadata'));
  await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(host.textContent).not.toContain('private encrypted metadata');
});

it('does not report a late failure after disposal or a replaced authorized read',async()=>{
  const availability=vi.fn();let reject!:(cause:unknown)=>void;
  const api:CreatorReviewApi={read:vi.fn().mockImplementationOnce(()=>new Promise((_resolve,no)=>reject=no)).mockResolvedValue(view),decide:vi.fn()};
  dispose=mountCreatorReview(host,api,{onAvailability:availability});
  // Exercise the request-generation guard independently of the disabled UI.
  host.querySelector<HTMLButtonElement>('[data-review-action="refresh"]')!.disabled=false;refresh();
  await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('ready'));
  reject(new Error('stale response'));await Promise.resolve();await Promise.resolve();
  expect(availability.mock.calls).toEqual([['loading'],['ready']]);
  dispose();dispose=undefined;expect(host.childElementCount).toBe(0);
  const afterDispose=vi.fn();let finish!:(value:CreatorReviewView)=>void;
  dispose=mountCreatorReview(host,{read:()=>new Promise(resolve=>finish=resolve),decide:vi.fn()},{onAvailability:afterDispose});
  dispose();dispose=undefined;finish(view);await Promise.resolve();await Promise.resolve();
  expect(afterDispose.mock.calls).toEqual([['loading']]);expect(host.childElementCount).toBe(0);
});

it('keeps a passive availability observer from changing the authorized review result',async()=>{
  const availability=vi.fn(()=>{throw new Error('observer failed');});
  dispose=mountCreatorReview(host,{read:vi.fn().mockResolvedValue(view),decide:vi.fn()},{onAvailability:availability});
  await vi.waitFor(()=>expect(host.textContent).toContain('Transcribing your recording'));
  expect(host.textContent).not.toContain('This recording is unavailable');expect(availability).toHaveBeenLastCalledWith('ready');
});

it('does not repopulate a disposed view when the host closes it during an availability notification',async()=>{
  const availability=vi.fn((state:string)=>{if(state==='unavailable')dispose?.();});
  dispose=mountCreatorReview(host,{read:vi.fn().mockRejectedValue(new Error('private unavailable')),decide:vi.fn()},{onAvailability:availability});
  await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(host.childElementCount).toBe(0);
});

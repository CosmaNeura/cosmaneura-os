import {afterEach,expect,it,vi} from 'vitest';
import {nativePresentationFeedback,setNativePresentation} from './native-presentation';
afterEach(()=>vi.unstubAllGlobals());
it('is inert in browsers and older shells',()=>{expect(()=>{setNativePresentation('messages');nativePresentationFeedback('send');}).not.toThrow();});
it('sends only closed presentation hints from the current generated document',()=>{
  const postMessage=vi.fn();vi.stubGlobal('__cosmasWorkspaceGeneration','invented-generation');vi.stubGlobal('webkit',{messageHandlers:{cosmasPresentation:{postMessage}}});
  setNativePresentation('messages');nativePresentationFeedback('success');
  expect(postMessage.mock.calls).toEqual([[{kind:'mode',value:'messages',generation:'invented-generation'}],[{kind:'feedback',value:'success',generation:'invented-generation'}]]);
});
it('a failed optional bridge never rejects a workflow',()=>{
  vi.stubGlobal('__cosmasWorkspaceGeneration','invented-generation');vi.stubGlobal('webkit',{messageHandlers:{cosmasPresentation:{postMessage:()=>{throw new Error('Shell unavailable');}}}});
  expect(()=>nativePresentationFeedback('warning')).not.toThrow();
});

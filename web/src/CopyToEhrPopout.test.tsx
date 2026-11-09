import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CopyToEhrPopout,supportsDocumentPictureInPicture} from './CopyToEhrPopout';

let root:Root,host:HTMLDivElement;
async function render(extra:Partial<Parameters<typeof CopyToEhrPopout>[0]>={}){
  await act(async()=>root.render(<CopyToEhrPopout sectionLabel="Subjective" sectionIndex={0} sectionCount={4} {...extra}/>));
}
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>item.textContent===label);

beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('shows split-screen guidance when Document Picture-in-Picture is missing',async()=>{
  expect(supportsDocumentPictureInPicture()).toBe(false);
  await render();
  await act(async()=>button('Pop out')!.click());
  expect(host.querySelector('.copy-to-ehr-guidance')?.textContent).toContain('split screen');
  expect(host.textContent).toContain('iPad');
  expect(host.textContent).not.toMatch(/integrat|sync|write-?back/i);
});

it('opens a Document Picture-in-Picture window when the API is present',async()=>{
  const pipDoc=document.implementation.createHTMLDocument('pip');
  const pipWindow={
    document:pipDoc,
    closed:false,
    close:vi.fn(),
    addEventListener:vi.fn(),
  } as unknown as Window;
  const requestWindow=vi.fn(async()=>pipWindow);
  vi.stubGlobal('documentPictureInPicture',{requestWindow,window:null});
  Object.defineProperty(window,'documentPictureInPicture',{configurable:true,value:{requestWindow,window:null}});
  await render();
  await act(async()=>button('Pop out')!.click());
  expect(requestWindow).toHaveBeenCalledOnce();
  expect(host.querySelector('[role=status]')?.textContent).toContain('Floating copy list is open');
  expect(pipDoc.getElementById('copy-to-ehr-pip-label')?.textContent).toContain('Next: Subjective');
  expect(pipDoc.body.textContent).not.toMatch(/integrat|sync|write-?back/i);
});

it('keeps Pop out disabled when the strip is locked',async()=>{
  await render({disabled:true});
  expect(button('Pop out')?.disabled).toBe(true);
  await act(async()=>button('Pop out')!.click());
  expect(host.querySelector('.copy-to-ehr-guidance')).toBeNull();
});

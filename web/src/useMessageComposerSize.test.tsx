import {act,useRef} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {useMessageComposerSize} from './useMessageComposerSize';
let root:Root,host:HTMLDivElement,height=44;
function Composer({text,active=true}:{text:string;active?:boolean}){const ref=useRef<HTMLTextAreaElement>(null);useMessageComposerSize(ref,active,text,'invented:chief');return <textarea ref={ref} value={text} readOnly style={{fontSize:16,lineHeight:'24px',padding:'6px'}}/>;}
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('CSS',{supports:()=>false});height=44;vi.spyOn(HTMLTextAreaElement.prototype,'scrollHeight','get').mockImplementation(()=>height);host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
const field=()=>host.querySelector('textarea')!;
async function render(text:string,active=true){await act(async()=>root.render(<Composer text={text} active={active}/>));}
it('grows for a pasted draft, caps at five lines, and shrinks after sending',async()=>{
  await render('');expect(field().style.height).toBe('44px');const retained=field();
  height=84;await render('Three invented lines');expect(field().style.height).toBe('84px');
  height=300;await render('A long invented draft');expect(field().style.height).toBe('132px');expect(field().style.overflowY).toBe('auto');
  height=44;await render('');expect(field()).toBe(retained);expect(field().style.height).toBe('44px');expect(field().style.overflowY).toBe('hidden');
});
it('releases presentation sizing when switching to Workspace without replacing the field or text',async()=>{
  height=96;await render('Keep this draft');const retained=field();await render('Keep this draft',false);
  expect(field()).toBe(retained);expect(field().value).toBe('Keep this draft');expect(field().style.height).toBe('');expect(field().style.maxHeight).toBe('');
});
it('uses native content sizing when available so dynamic font changes can resize the composer',async()=>{
  vi.stubGlobal('CSS',{supports:()=>true});await render('A retained draft');expect(field().style.height).toBe('');expect(field().style.maxHeight).toBe('');
});

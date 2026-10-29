import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {CHIEF_STARTERS,ChiefStartActions,InitialTeamAction} from './ChiefStartActions';

describe('Chief first-use controls',()=>{
  let container:HTMLDivElement,root:Root;
  const ready={locked:false,modelEnabled:true,sourceAllowed:true,hasSavedContext:true,notesDirty:false,hasQuestion:false,canDelegate:true};
  beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});container=document.createElement('div');document.body.append(container);root=createRoot(container);});
  afterEach(async()=>{await act(async()=>root.unmount());container.remove();});
  it('offers editable requests and never starts one during rendering',async()=>{
    const choose=vi.fn();await act(async()=>root.render(<ChiefStartActions {...ready} onChoose={choose}/>));
    expect(choose).not.toHaveBeenCalled();
    const buttons=[...container.querySelectorAll('button')];
    expect(buttons.map(button=>button.textContent)).toEqual(CHIEF_STARTERS.map(task=>task.label));
    await act(async()=>buttons[2].click());expect(choose).toHaveBeenCalledExactlyOnceWith(CHIEF_STARTERS[2].prompt);
    expect(container.textContent).toContain('review the question');
  });
  it('keeps Messages starters to two editable choices without a disclosure menu',async()=>{
    const choose=vi.fn();await act(async()=>root.render(<ChiefStartActions {...ready} minimal onChoose={choose}/>));
    expect(container.querySelectorAll('button')).toHaveLength(2);expect(container.querySelector('details')).toBeNull();expect(choose).not.toHaveBeenCalled();
    await act(async()=>container.querySelector('button')!.click());expect(choose).toHaveBeenCalledExactlyOnceWith(CHIEF_STARTERS[0].prompt);
  });
  it.each([{modelEnabled:false},{sourceAllowed:false},{hasSavedContext:false},{notesDirty:true},{hasQuestion:true},{locked:true}])('keeps requests gated by %j',async(change)=>{
    const choose=vi.fn();await act(async()=>root.render(<ChiefStartActions {...ready} {...change} onChoose={choose}/>));
    for(const button of container.querySelectorAll('button')){expect(button.disabled).toBe(true);await act(async()=>button.click());}
    expect(choose).not.toHaveBeenCalled();
  });
  it('blocks only team assignments when Chief cannot delegate',async()=>{
    await act(async()=>root.render(<ChiefStartActions {...ready} canDelegate={false} onChoose={vi.fn()}/>));
    expect([...container.querySelectorAll('button')].map(button=>button.disabled)).toEqual([false,false,true,true]);
    expect(container.textContent).toContain('Private team assignments are off');
  });
  it('accepts the displayed default team only after an explicit click',async()=>{
    const use=vi.fn(),settings=vi.fn();await act(async()=>root.render(<InitialTeamAction names={['Chief','Scribe']} locked={false} unchanged onUse={use} onSettings={settings}/>));
    expect(use).not.toHaveBeenCalled();expect(container.textContent).toContain('Chief · Scribe');expect(container.textContent).not.toContain('Research');
    await act(async()=>container.querySelector('button')!.click());expect(use).toHaveBeenCalledOnce();expect(settings).not.toHaveBeenCalled();
  });
  it('retains a modified team draft for the existing review path',async()=>{
    const use=vi.fn(),settings=vi.fn();await act(async()=>root.render(<InitialTeamAction names={['Chief']} locked={false} unchanged={false} onUse={use} onSettings={settings}/>));
    const button=container.querySelector('button')!;expect(button.textContent).toBe('Review team changes');
    await act(async()=>button.click());expect(settings).toHaveBeenCalledOnce();expect(use).not.toHaveBeenCalled();
  });
  it('keeps Ask Chief and starter taps at least 44px',async()=>{
    await act(async()=>root.render(<ChiefStartActions {...ready} onChoose={vi.fn()}/>));
    const {readFileSync}=await vi.importActual<{readFileSync:(path:string,encoding:'utf8')=>string}>('node:fs');const {fileURLToPath}=await vi.importActual<{fileURLToPath:(url:string)=>string}>('node:url');
    const css=readFileSync(fileURLToPath(import.meta.url).replace(/[^/]+$/,'chief-start-actions.css'),'utf8');
    expect(css).toMatch(/\.chief-ask-summary[^}]*min-height:\s*44px/);
    expect(css).toMatch(/\.chief-start-actions button[^}]*min-height:\s*44px/);
  });
});

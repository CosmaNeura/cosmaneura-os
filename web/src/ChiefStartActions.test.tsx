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
  it('makes an empty Chief conversation actionable without creating or replacing a request',async()=>{
    const choose=vi.fn(),open=vi.fn();await act(async()=>root.render(<ChiefStartActions {...ready} minimal hasSavedContext={false} hasQuestion onChoose={choose} onOpenNotebook={open}/>));
    const buttons=[...container.querySelectorAll('button')];expect(buttons.map(button=>button.textContent)).toEqual(['Add notes']);
    expect(container.textContent).toContain('Your message draft stays here.');expect(open).not.toHaveBeenCalled();expect(choose).not.toHaveBeenCalled();
    await act(async()=>buttons[0].click());expect(open).toHaveBeenCalledOnce();expect(choose).not.toHaveBeenCalled();
    await act(async()=>root.render(<ChiefStartActions {...ready} minimal onChoose={choose} onOpenNotebook={open}/>));
    expect([...container.querySelectorAll('button')].map(button=>button.textContent)).toEqual(CHIEF_STARTERS.slice(0,2).map(task=>task.label));
  });
  it('keeps the notebook shortcut blocked while navigation is locked',async()=>{
    const open=vi.fn();await act(async()=>root.render(<ChiefStartActions {...ready} minimal locked hasSavedContext={false} onChoose={vi.fn()} onOpenNotebook={open}/>));
    const button=container.querySelector('button')!;expect(button.disabled).toBe(true);await act(async()=>button.click());expect(open).not.toHaveBeenCalled();
  });
  it.each([true,false])('offers source-choice review without replacing an unsent question or changing access: minimal=%s',async minimal=>{
    const choose=vi.fn(),review=vi.fn();await act(async()=>root.render(<ChiefStartActions {...ready} minimal={minimal} sourceAllowed={false} hasQuestion onChoose={choose} onReviewSources={review}/>));
    const buttons=[...container.querySelectorAll('button')];expect(buttons.map(button=>button.textContent)).toEqual([...(minimal?[]:CHIEF_STARTERS.map(task=>task.label)),'Review source choices']);if(minimal)expect(container.textContent).toContain('Your message draft stays here.');else expect(buttons.slice(0,4).every(button=>button.disabled)).toBe(true);expect(review).not.toHaveBeenCalled();
    await act(async()=>buttons.at(-1)!.click());expect(review).toHaveBeenCalledOnce();expect(choose).not.toHaveBeenCalled();
  });
  it.each([{locked:true},{notesDirty:true},{reviewSourcesLocked:true}])('blocks source-choice navigation for %j',async change=>{
    const review=vi.fn();await act(async()=>root.render(<ChiefStartActions {...ready} {...change} minimal sourceAllowed={false} onChoose={vi.fn()} onReviewSources={review}/>));
    const button=container.querySelector('button')!;expect(button.textContent).toBe('Review source choices');expect(button.disabled).toBe(true);await act(async()=>button.click());expect(review).not.toHaveBeenCalled();
  });
  it.each([{modelEnabled:false},{sourceAllowed:false}])('retains unavailable-context guidance for %j instead of offering a misleading next step',async change=>{
    const open=vi.fn();await act(async()=>root.render(<ChiefStartActions {...ready} {...change} minimal hasSavedContext={false} onChoose={vi.fn()} onOpenNotebook={open}/>));
    expect(container.textContent).not.toContain('Add notes');expect([...container.querySelectorAll('button')].every(button=>button.disabled)).toBe(true);expect(open).not.toHaveBeenCalled();
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

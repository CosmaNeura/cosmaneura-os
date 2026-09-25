import {act,useEffect,useState} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {WorkspaceRuntimeErrorBoundary} from "./runtime";

let root:Root,element:HTMLDivElement;
beforeEach(()=>{vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);element=document.createElement('div');document.body.append(element);
 root=createRoot(element,{onCaughtError:()=>{}});
});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.unstubAllGlobals();});

it('replaces an already loaded workspace with truthful recovery guidance without clearing saved requests or mounting again',async()=>{
 const retained={pending:{key:'invented-original-request'},note:'Invented private saved text'},before=structuredClone(retained);
 const cleanup=vi.fn(),mount=vi.fn(),send=vi.fn();
 function LoadedWorkspace(){
   const [failed,setFailed]=useState(false);useEffect(()=>{mount();return cleanup;},[]);
   if(failed)throw Error('PRIVATE transcript and token must not be displayed');
   return <><p>{retained.note}</p><button onClick={()=>{send();setFailed(true);}}>Invented failing action</button></>;
 }
 await act(async()=>root.render(<WorkspaceRuntimeErrorBoundary><LoadedWorkspace/></WorkspaceRuntimeErrorBoundary>));
 expect(element.textContent).toContain(retained.note);
 await act(async()=>element.querySelector('button')!.click());
 expect(element.textContent).toContain('Your workspace could not continue');expect(element.textContent).toContain('submitted work may still finish');
 expect(element.textContent).not.toMatch(/No work has been loaded|PRIVATE transcript|Invented private saved text/);
 expect(retained).toEqual(before);expect(cleanup).toHaveBeenCalledOnce();expect(send).toHaveBeenCalledOnce();
 await act(async()=>root.render(<WorkspaceRuntimeErrorBoundary><LoadedWorkspace/></WorkspaceRuntimeErrorBoundary>));
 expect(mount).toHaveBeenCalledOnce();expect(send).toHaveBeenCalledOnce();expect(element.querySelector('button')).toBeNull();
});

it('handles an exception during initial child rendering with the same private-data-free guidance',async()=>{
 function Broken(){throw Error('PRIVATE identity provider detail');return null;}
 await act(async()=>root.render(<WorkspaceRuntimeErrorBoundary><Broken/></WorkspaceRuntimeErrorBoundary>));
 expect(element.querySelector('[role="alert"]')).toBeTruthy();expect(element.textContent).toContain('unconfirmed requests before retrying');
 expect(element.textContent).not.toContain('PRIVATE identity');
});

import {act, StrictMode} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach, beforeEach, expect, it} from "vitest";
import {hasUnsavedWork, useUnsavedWork} from "./unsaved-work";

let root:Root, container:HTMLDivElement;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});container=document.createElement("div");document.body.append(container);root=createRoot(container);});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();expect(hasUnsavedWork()).toBe(false);});
function Editor({dirty}:{dirty:boolean}) {useUnsavedWork(dirty);return null;}
const blocked=()=>!window.dispatchEvent(new Event("beforeunload",{cancelable:true}));

it("keeps the unload guard until every independent editor or pending request clears",async()=>{
 await act(async()=>root.render(<><Editor dirty/><Editor dirty/></>));
 expect(blocked()).toBe(true);
 await act(async()=>root.render(<><Editor dirty={false}/><Editor dirty/></>));
 expect(blocked()).toBe(true);
 await act(async()=>root.render(<><Editor dirty={false}/><Editor dirty={false}/></>));
 expect(blocked()).toBe(false);
});
it("cleans up an unmounted or replaced account without retaining private editor data",async()=>{
 await act(async()=>root.render(<StrictMode><Editor key="old-account" dirty/></StrictMode>));
 expect(hasUnsavedWork()).toBe(true);
 await act(async()=>root.render(<StrictMode><Editor key="new-account" dirty={false}/></StrictMode>));
 expect(hasUnsavedWork()).toBe(false);expect(blocked()).toBe(false);
});

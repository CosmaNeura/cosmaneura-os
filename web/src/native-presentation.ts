/** Presentation-only hints. No content, identity, credentials or save commands
 * cross this bridge. Ordinary browsers and older shells simply ignore them. */
type NativePresentationWindow=Window & {__cosmasWorkspaceGeneration?:string;webkit?:{messageHandlers?:{cosmasPresentation?:{postMessage:(value:unknown)=>void}}}};
function post(kind:'mode'|'feedback',value:string){
  if(typeof window==='undefined')return;
  const native=window as NativePresentationWindow,generation=native.__cosmasWorkspaceGeneration;
  if(!generation||window.top!==window)return;
  try{native.webkit?.messageHandlers?.cosmasPresentation?.postMessage({kind,value,generation});}catch{/* Presentation feedback never changes workflow outcomes. */}
}
export function setNativePresentation(value:'messages'|'workspace'){post('mode',value);}
export function nativePresentationFeedback(value:'send'|'selection'|'success'|'warning'){post('feedback',value);}

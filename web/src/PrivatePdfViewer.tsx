import {useEffect,useId,useRef,useState} from 'react';
import type {Document as StoredDocument} from './vendor-schema';
import {openPrivatePdf,privatePdfLayout,PDF_REVIEW_MAX_ZOOM,type PdfDocument} from './private-pdf';
import './private-pdf.css';

export type PrivatePdfViewerProps={bytes:Uint8Array;document:StoredDocument;title?:string;onReviewReady?:(ready:boolean)=>void};
/** A successful render of every page permits a separate human review checkbox; it never gives consent. */
export function PrivatePdfViewer({bytes,document,title='Verified private PDF',onReviewReady}:PrivatePdfViewerProps){
 const [doc,setDoc]=useState<PdfDocument|null>(null),[page,setPage]=useState(1),[loaded,setLoaded]=useState(0),[error,setError]=useState(''),[busy,setBusy]=useState(true),[width,setWidth]=useState(600),[zoom,setZoom]=useState(1);
 const [textOpen,setTextOpen]=useState(false),[text,setText]=useState<{doc:PdfDocument;page:number;value:string;error:string;busy:boolean}|null>(null);
 const canvas=useRef<HTMLCanvasElement>(null),holder=useRef<HTMLDivElement>(null),visited=useRef(new Set<number>()),callback=useRef(onReviewReady),binding=useRef<{bytes:Uint8Array;document:StoredDocument;doc:PdfDocument}|null>(null),textId=useId(),panId=useId();
 callback.current=onReviewReady;
 const sourceCurrent=binding.current?.bytes===bytes&&binding.current.document===document&&binding.current.doc===doc;
 useEffect(()=>{const node=holder.current;if(!node)return;setWidth(node.clientWidth||600);if(typeof ResizeObserver==='undefined')return;const observer=new ResizeObserver(entries=>setWidth(entries[0]?.contentRect.width||600));observer.observe(node);return()=>observer.disconnect();},[]);
 useEffect(()=>{
  const controller=new AbortController();let current:PdfDocument|null=null,active=true;visited.current=new Set();setLoaded(0);setPage(1);setZoom(1);setTextOpen(false);setText(null);setDoc(null);setError('');setBusy(true);callback.current?.(false);
  const timer=setTimeout(()=>{controller.abort();if(active){setError('This PDF took too long to open. Reopen it to try again.');setBusy(false);callback.current?.(false);}},20_000);
  void openPrivatePdf(bytes,document,controller.signal).then(value=>{if(controller.signal.aborted||!active){void value.destroy();return;}current=value;binding.current={bytes,document,doc:value};setDoc(value);}).catch(()=>{if(active){setError('This PDF could not be opened for review. Choose a supported, unencrypted PDF.');setBusy(false);callback.current?.(false);}}).finally(()=>clearTimeout(timer));
  return()=>{active=false;controller.abort();clearTimeout(timer);if(current)void current.destroy().catch(()=>{});};
 },[bytes,document]);
 useEffect(()=>{
  if(!doc||!sourceCurrent||!canvas.current)return;let active=true,cancel:(()=>void)|undefined;setBusy(true);setError('');visited.current.delete(page);setLoaded(visited.current.size);callback.current?.(false);
  const timer=setTimeout(()=>{if(!active)return;active=false;cancel?.();setError('This page took too long to display. Reopen the document to try again.');setBusy(false);callback.current?.(false);},20_000);
  const target=canvas.current;target.width=0;target.height=0;
  void doc.getPage(page).then(async value=>{
   try{
    if(!active)return;const natural=value.getViewport({scale:1}),layout=privatePdfLayout(natural.width,natural.height,width,window.devicePixelRatio||1,zoom),viewport=value.getViewport({scale:layout.scale});
    target.width=layout.pixelWidth;target.height=layout.pixelHeight;target.style.width=layout.cssWidth+'px';target.style.height=layout.cssHeight+'px';
    const context=target.getContext('2d',{alpha:false});if(!context)throw new Error('Canvas unavailable');
    const render=value.render({canvas:target,canvasContext:context,viewport});cancel=()=>render.cancel();await render.promise;await value.verifyImages();
    if(active){visited.current.add(page);setLoaded(visited.current.size);setBusy(false);callback.current?.(visited.current.size===doc.numPages);}
   }finally{value.cleanup();}
  }).catch(()=>{if(active){setError('This page could not be displayed. Review remains incomplete.');setBusy(false);callback.current?.(false);}}).finally(()=>clearTimeout(timer));
  return()=>{active=false;clearTimeout(timer);cancel?.();target.width=0;target.height=0;};
 },[doc,page,width,zoom,sourceCurrent]);
 useEffect(()=>{
  if(!textOpen||!doc||!sourceCurrent)return;let active=true;const controller=new AbortController();setText({doc,page,value:'',error:'',busy:true});
  const timer=setTimeout(()=>{controller.abort();if(active)setText({doc,page,value:'',error:'Page text took too long to load. Close it and try again.',busy:false});},20_000);
  void doc.getPage(page).then(value=>value.readText(controller.signal)).then(value=>{if(active&&!controller.signal.aborted)setText({doc,page,value,error:'',busy:false});}).catch(()=>{if(active&&!controller.signal.aborted)setText({doc,page,value:'',error:'Page text is unavailable. Use the page image to review this document.',busy:false});}).finally(()=>clearTimeout(timer));
  return()=>{active=false;clearTimeout(timer);controller.abort();};
 },[doc,page,textOpen,sourceCurrent]);
 const move=(next:number)=>{setTextOpen(false);setText(null);setPage(next);if(holder.current){holder.current.scrollLeft=0;holder.current.scrollTop=0;}};
 const fit=()=>{setZoom(1);if(holder.current){holder.current.scrollLeft=0;holder.current.scrollTop=0;}};
 const currentText=text?.doc===doc&&text.page===page?text:null;
 return <section className="private-pdf-viewer" aria-label={title}>
  <div className="private-pdf-controls"><button type="button" disabled={!doc||!sourceCurrent||busy||page===1} onClick={()=>move(page-1)}>Previous PDF page</button><span aria-live="polite">{doc?'Page '+page+' of '+doc.numPages:'Opening PDF'}</span><button type="button" disabled={!doc||!sourceCurrent||busy||page===doc.numPages} onClick={()=>move(page+1)}>Next PDF page</button></div>
  <div className="private-pdf-controls private-pdf-zoom" role="group" aria-label="PDF zoom"><button type="button" disabled={!doc||!sourceCurrent||busy||zoom===1} onClick={()=>setZoom(value=>Math.max(1,value-.5))}>Zoom out</button><span aria-live="polite">{zoom===1?'Fit width':Math.round(zoom*100)+'% of fit width'}</span><button type="button" disabled={!doc||!sourceCurrent||busy||zoom===PDF_REVIEW_MAX_ZOOM} onClick={()=>setZoom(value=>Math.min(PDF_REVIEW_MAX_ZOOM,value+.5))}>Zoom in</button><button type="button" disabled={!doc||!sourceCurrent||busy||zoom===1} onClick={fit}>Fit width</button></div>
  <p role={error?'alert':'status'}>{error|| (busy?'Displaying private PDF…':loaded===doc?.numPages?'All pages displayed. Review the document before confirming.':loaded+' of '+(doc?.numPages??0)+' pages displayed. Visit each page before confirming review.')}</p>
  <p id={panId} className="private-pdf-pan-hint">Zoom in for larger text. Swipe or use arrow keys in the page area to move around.</p>
  <div className="private-pdf-viewport" ref={holder} role="region" aria-label="PDF page area" aria-describedby={panId} tabIndex={0} aria-busy={busy}>
   <canvas ref={canvas} aria-label={title+', page '+page} role="img" hidden={!sourceCurrent||busy||!!error}/>
  </div>
  <button type="button" disabled={!doc||!sourceCurrent||busy||!!error} aria-expanded={textOpen} aria-controls={textId} onClick={()=>setTextOpen(value=>!value)}>{textOpen?'Hide page text':'Read page text'}</button>
  {textOpen&&sourceCurrent&&<div id={textId} className="private-pdf-text" role="region" aria-label={'Page '+page+' text'}><p>Extracted text may use a different reading order. Review the page image for layout and images.</p>{currentText?.error?<p role="alert">{currentText.error}</p>:currentText?.busy||!currentText?<p role="status">Reading page text…</p>:<pre>{currentText.value||'No readable text was found on this page.'}</pre>}</div>}
 </section>;
}

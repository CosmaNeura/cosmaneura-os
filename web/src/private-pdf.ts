import type {Document} from './vendor-schema';
import {requirePdf} from './vendor-api';

export const PDF_REVIEW_MAX_PAGES=100;
export const PDF_REVIEW_MAX_PIXELS=4_000_000;
export const PDF_REVIEW_MAX_ZOOM=4;
export const PDF_REVIEW_MAX_TEXT=32_768;
export type PdfViewport={width:number;height:number};
export type PdfPage={getViewport:(options:{scale:number})=>PdfViewport;render:(options:{canvas:HTMLCanvasElement;canvasContext:CanvasRenderingContext2D;viewport:PdfViewport})=>{promise:Promise<void>;cancel:()=>void};verifyImages:()=>Promise<void>;readText:(signal:AbortSignal)=>Promise<string>;cleanup:()=>void};
export type PdfDocument={numPages:number;getPage:(page:number)=>Promise<PdfPage>;destroy:()=>Promise<void>};
type ParsedPage=Omit<PdfPage,'verifyImages'|'readText'>&{streamTextContent:(options:{includeMarkedContent:false})=>ReadableStream<{items:unknown[]}>;getOperatorList:()=>Promise<{fnArray:number[];argsArray:unknown[][]}>;objs:{get:(id:string)=>unknown};commonObjs:{get:(id:string)=>unknown}};
type ParsedDocument=Omit<PdfDocument,'getPage'>&{getPage:(page:number)=>Promise<ParsedPage>};
type PdfLoading={promise:Promise<ParsedDocument>;destroy:()=>Promise<void>};
type PdfWorker={destroy:()=>void};
type PdfModule={version:string;OPS:{paintImageXObject:number;paintImageXObjectRepeat:number;setFont:number};PDFWorker:new(options:{port:Worker})=>PdfWorker;getDocument:(options:Record<string,unknown>)=>PdfLoading};
let library:Promise<PdfModule>|undefined;
function localResources(){
 const base=new URL(`${import.meta.env.BASE_URL??'/'}vendor/pdfjs-5.6.205/`,window.location.href);
 if(base.protocol!==window.location.protocol||base.host!==window.location.host||!['http:','https:','app:','capacitor:'].includes(base.protocol))throw new Error('Private PDF resources are unavailable.');
 return base;
}
/** Parses only previously authorized exact bytes. All parser/font resources are packaged locally. */
export async function openPrivatePdf(bytes:Uint8Array,document:Document,signal:AbortSignal):Promise<PdfDocument>{
 await requirePdf(document,bytes);signal.throwIfAborted();
 const base=localResources(),moduleUrl=new URL('pdf.mjs',base).href;
 library??=import(/* @vite-ignore */ moduleUrl).then(value=>{if(value.version!=='5.6.205')throw new Error('Private PDF resources do not match.');return value as PdfModule;}).catch(error=>{library=undefined;throw error;});
 const pdf=await library;signal.throwIfAborted();
 // Explicit port avoids PDF.js's blob/CDN wrapper for app:// and capacitor://.
 const port=new Worker(new URL('pdf.worker.mjs',base),{type:'module',name:'cosmas-private-pdf'});let worker:PdfWorker,task:PdfLoading;
 try{worker=new pdf.PDFWorker({port});task=pdf.getDocument({worker,data:new Uint8Array(bytes),isEvalSupported:false,useWasm:false,enableXfa:false,stopAtErrors:true,disableAutoFetch:true,disableStream:true,disableRange:true,useWorkerFetch:false,isImageDecoderSupported:false,isOffscreenCanvasSupported:false,disableFontFace:true,cMapUrl:new URL('cmaps/',base).href,cMapPacked:true,standardFontDataUrl:new URL('standard_fonts/',base).href,wasmUrl:new URL('wasm/',base).href,maxImageSize:16_000_000,canvasMaxAreaInBytes:PDF_REVIEW_MAX_PIXELS*4,verbosity:0});}catch(error){port.terminate();throw error;}
 let destroyed=false;const destroy=async()=>{if(destroyed)return;destroyed=true;void task.destroy().catch(()=>{});worker.destroy();port.terminate();};
 const abort=()=>{void destroy();};signal.addEventListener('abort',abort,{once:true});
 try{const doc=await task.promise;signal.throwIfAborted();if(!Number.isSafeInteger(doc.numPages)||doc.numPages<1||doc.numPages>PDF_REVIEW_MAX_PAGES){await destroy();throw new Error('This PDF exceeds the private review page limit.');}return {numPages:doc.numPages,getPage:async number=>{const page=await doc.getPage(number);return {getViewport:options=>page.getViewport(options),render:options=>page.render(options),cleanup:()=>page.cleanup(),verifyImages:()=>requireRenderedPdfImages(page,pdf.OPS),readText:signal=>{signal.throwIfAborted();return readPrivatePdfText(page.streamTextContent({includeMarkedContent:false}),signal);}};},destroy};}catch(error){abort();throw error;}finally{signal.removeEventListener('abort',abort);}
}
/** PDF.js can resolve render() after a decoder supplies null. Such pages are not reviewable. */
export async function requireRenderedPdfImages(page:Pick<ParsedPage,'getOperatorList'|'objs'|'commonObjs'>,ops:PdfModule['OPS']){
 let count=0;const checkedFonts=new Set<string>(),activeFonts=new Set<string>();
 const walk=(value:unknown,depth:number)=>{
  if(depth>8||!value||typeof value!=='object'||!('fnArray'in value)||!('argsArray'in value)||!Array.isArray(value.fnArray)||!Array.isArray(value.argsArray)||value.fnArray.length!==value.argsArray.length)throw new Error('PDF page is too complex.');
  count+=value.fnArray.length+1;if(count>200_000)throw new Error('PDF page is too complex.');
  for(let index=0;index<value.fnArray.length;index++){
   const op=value.fnArray[index],args=value.argsArray[index];
   // Tiling patterns retain their own operator list in the pinned PDF.js IR.
   if(Array.isArray(args)&&args[0]==='TilingPattern')walk(args[2],depth+1);
   if(op===ops.paintImageXObject||op===ops.paintImageXObjectRepeat){
    const id=Array.isArray(args)?args[0]:undefined;
    if(typeof id!=='string'||!(id.startsWith('g_')?page.commonObjs:page.objs).get(id))throw new Error('A PDF image could not be decoded.');
   }
   if(op===ops.setFont){
    const id=Array.isArray(args)?args[0]:undefined;if(typeof id!=='string')throw new Error('A PDF font could not be rendered.');
    if(activeFonts.has(id))throw new Error('Recursive PDF fonts are not supported.');if(checkedFonts.has(id))continue;
    const font=page.commonObjs.get(id);
    if(!font||typeof font!=='object'||('isInvalidPDFjsFont'in font&&font.isInvalidPDFjsFont===true))throw new Error('A PDF font could not be rendered.');
    if('isType3Font'in font&&font.isType3Font===true){
     const glyphs='charProcOperatorList'in font?font.charProcOperatorList:null;
     if(!glyphs||typeof glyphs!=='object'||Array.isArray(glyphs)||Object.keys(glyphs).length>4096)throw new Error('A PDF font could not be rendered.');
     activeFonts.add(id);for(const glyph of Object.values(glyphs))walk(glyph,depth+1);activeFonts.delete(id);
    }
    checkedFonts.add(id);
   }
  }
 };
 walk(await page.getOperatorList(),0);
}
/** Fit-width CSS and raster dimensions are separate, so zoom pans rather than widening the page layout. */
export function privatePdfLayout(width:number,height:number,available:number,density:number,zoom=1){
 if(![width,height,available,density,zoom].every(Number.isFinite)||width<=0||height<=0||width>14400||height>14400||available<=0||density<=0||zoom<1||zoom>PDF_REVIEW_MAX_ZOOM)throw new Error('Unsupported PDF page dimensions.');
 const fit=Math.min(Math.min(available,1000)/width,2048/Math.max(width,height)),cssScale=fit*zoom;
 // Reserve rounding space so ceil(width/height) also stays within the raster budget.
 const scale=Math.min(cssScale*Math.min(Math.max(density,1),2),Math.sqrt((PDF_REVIEW_MAX_PIXELS-8192)/(width*height)),4095/Math.max(width,height));
 return {scale,cssWidth:width*cssScale,cssHeight:height*cssScale,pixelWidth:Math.max(1,Math.ceil(width*scale)),pixelHeight:Math.max(1,Math.ceil(height*scale))};
}
export function privatePdfScale(width:number,height:number,available:number,density:number,zoom=1){return privatePdfLayout(width,height,available,density,zoom).scale;}

/** Supplemental text only: bounded chunks, escaped by React, no links or PDF actions. */
export async function readPrivatePdfText(stream:ReadableStream<{items:unknown[]}>,signal:AbortSignal):Promise<string>{
 signal.throwIfAborted();const reader=stream.getReader();let count=0,length=0;const output:string[]=[];
 const stop=()=>{try{void reader.cancel().catch(()=>{});}catch{}};
 let rejectAbort!:(reason:unknown)=>void;const interrupted=new Promise<never>((_,reject)=>{rejectAbort=reject;});void interrupted.catch(()=>{});
 const abort=()=>{stop();rejectAbort(new Error('Page text unavailable.'));};signal.addEventListener('abort',abort,{once:true});
 try{for(;;){signal.throwIfAborted();const next=await Promise.race([reader.read(),interrupted]);signal.throwIfAborted();if(next.done)break;
   if(!next.value||!Array.isArray(next.value.items)||next.value.items.length>4096-count)throw new Error('Page text exceeds the reading limit.');
   for(const item of next.value.items){count++;if(!item||typeof item!=='object'||!('str'in item)||typeof item.str!=='string'||item.str.length>4096)throw new Error('Page text unavailable.');
    const value=item.str+('hasEOL'in item&&item.hasEOL===true?'\n':' ');length+=value.length;if(length>PDF_REVIEW_MAX_TEXT)throw new Error('Page text exceeds the reading limit.');output.push(value);}
  }return output.join('').trim();
 }finally{signal.removeEventListener('abort',abort);stop();try{reader.releaseLock();}catch{}}
}

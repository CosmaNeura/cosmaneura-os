import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {PrivatePdfViewer} from './PrivatePdfViewer';
import {openPrivatePdf,privatePdfScale,privatePdfLayout,readPrivatePdfText,requireRenderedPdfImages,type PdfDocument,type PdfPage} from './private-pdf';
import type {Document as StoredDocument} from './vendor-schema';
vi.mock('./private-pdf',async()=>({...await vi.importActual('./private-pdf'),openPrivatePdf:vi.fn()}));
const metadata:StoredDocument={artifact_id:'00000000-0000-0000-0000-000000000001',media_type:'application/pdf',byte_length:10,sha256:'a'.repeat(64)};
describe('bounded private PDF review',()=>{
 let root:Root,host:HTMLDivElement,doc:PdfDocument,ready:ReturnType<typeof vi.fn>;
 const bytes=new Uint8Array(10);
 const flush=async()=>{await act(async()=>{await new Promise(r=>setTimeout(r,1));});};
 const page=():PdfPage=>({getViewport:({scale})=>({width:600*scale,height:800*scale}),render:()=>({promise:Promise.resolve(),cancel:vi.fn()}),verifyImages:async()=>{},readText:async()=>'<plain page text>',cleanup:vi.fn()});
 beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement('div');document.body.append(host);root=createRoot(host);ready=vi.fn();doc={numPages:2,getPage:vi.fn(async()=>page()),destroy:vi.fn(async()=>{})};vi.mocked(openPrivatePdf).mockResolvedValue(doc);vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({} as CanvasRenderingContext2D);});
 afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
 const button=(label:string)=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent===label)!;
 const click=async(label:string)=>{await act(async()=>button(label).click());await flush();};
 const mount=async(data=bytes,document=metadata)=>{await act(async()=>root.render(<PrivatePdfViewer bytes={data} document={document} onReviewReady={ready}/>));await flush();};
 it('requires every actual page render and keeps consent external',async()=>{await mount();expect(ready).not.toHaveBeenCalledWith(true);expect(host.textContent).toContain('1 of 2 pages displayed');await act(async()=>Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='Next PDF page')!.click());await flush();expect(ready).toHaveBeenLastCalledWith(true);expect(host.querySelector('input')).toBeNull();expect(host.querySelector('iframe')).toBeNull();});
 it('does not mark a rejected parser or password-protected file reviewed',async()=>{vi.mocked(openPrivatePdf).mockRejectedValueOnce(new Error('Password required'));await mount();expect(host.querySelector('[role=alert]')?.textContent).toContain('could not be opened');expect(ready).not.toHaveBeenCalledWith(true);});
 it('does not treat a partial page render as review',async()=>{doc.getPage=vi.fn(async()=>({...page(),render:()=>({promise:Promise.reject(new Error('Unsupported decoder')),cancel:vi.fn()})}));await mount();expect(host.querySelector('[role=alert]')?.textContent).toContain('could not be displayed');expect(ready).not.toHaveBeenCalledWith(true);expect(host.querySelector('canvas')?.hidden).toBe(true);});
 it('rejects silently omitted images after a resolved canvas render',async()=>{doc.getPage=vi.fn(async()=>({...page(),verifyImages:async()=>{throw new Error('Missing image');}}));await mount();expect(ready).not.toHaveBeenCalledWith(true);expect(host.querySelector('canvas')?.hidden).toBe(true);});
 it('checks both page-local and shared image objects',async()=>{const ops={paintImageXObject:85,paintImageXObjectRepeat:88,setFont:37},p={getOperatorList:async()=>({fnArray:[85,88],argsArray:[['img_1'],['g_2']]}),objs:{get:()=>({data:[]})},commonObjs:{get:()=>null as unknown}};await expect(requireRenderedPdfImages(p,ops)).rejects.toThrow('could not be decoded');p.commonObjs.get=()=>({data:[]});await expect(requireRenderedPdfImages(p,ops)).resolves.toBeUndefined();});
 it('fences late completion and destroys the parser on source change',async()=>{let complete!:()=>void;doc.numPages=1;doc.getPage=vi.fn(async()=>({...page(),render:()=>({promise:new Promise<void>(r=>{complete=r;}),cancel:vi.fn()})}));await mount();const old=doc;vi.mocked(openPrivatePdf).mockRejectedValueOnce(new Error('Changed source'));await mount(new Uint8Array(11),{...metadata,byte_length:11});await act(async()=>complete());expect(old.destroy).toHaveBeenCalled();expect(ready).not.toHaveBeenCalledWith(true);});
 it('clears render readiness when bytes change after a completed review',async()=>{doc.numPages=1;await mount();expect(ready).toHaveBeenLastCalledWith(true);vi.mocked(openPrivatePdf).mockRejectedValueOnce(new Error('Hash mismatch'));await mount(new Uint8Array(12),{...metadata,byte_length:12});expect(ready).toHaveBeenLastCalledWith(false);});
 it('never revives review after unmount',async()=>{let release!:(v:PdfDocument)=>void;vi.mocked(openPrivatePdf).mockImplementationOnce(()=>new Promise(r=>{release=r;}));await mount();await act(async()=>root.render(null));await act(async()=>release(doc));expect(doc.destroy).toHaveBeenCalled();expect(ready).not.toHaveBeenCalledWith(true);});

 it('zooms within a narrow focusable scroll viewport and returns to fit without changing consent',async()=>{
  vi.stubGlobal('ResizeObserver',class{constructor(private notify:(items:unknown[])=>void){}observe(){this.notify([{contentRect:{width:304}}]);}disconnect(){}});
  await mount();const target=host.querySelector('canvas')!,region=host.querySelector<HTMLDivElement>('.private-pdf-viewport')!;
  expect(region.tabIndex).toBe(0);expect(target.style.width).toBe('304px');expect(button('Zoom out').disabled).toBe(true);
  await click('Zoom in');expect(target.style.width).toBe('456px');expect(host.textContent).toContain('150% of fit width');expect(ready).not.toHaveBeenCalledWith(true);
  for(let n=0;n<5;n++)await click('Zoom in');
  expect(target.style.width).toBe('1216px');expect(button('Zoom in').disabled).toBe(true);expect(target.width*target.height).toBeLessThanOrEqual(4_000_000);
  region.scrollLeft=200;await click('Fit width');expect(region.scrollLeft).toBe(0);expect(target.style.width).toBe('304px');expect(button('Zoom out').disabled).toBe(true);
 });
 it('withholds completed review while a zoom render is unresolved and hides a failed zoom',async()=>{
  doc.numPages=1;await mount();expect(ready).toHaveBeenLastCalledWith(true);
  let reject!:(reason:Error)=>void;doc.getPage=vi.fn(async()=>({...page(),render:()=>({promise:new Promise<void>((_,no)=>{reject=no;}),cancel:vi.fn()})}));
  await click('Zoom in');expect(ready).toHaveBeenLastCalledWith(false);expect(host.querySelector('canvas')?.hidden).toBe(true);
  await act(async()=>reject(new Error('Zoom failed')));expect(ready).toHaveBeenLastCalledWith(false);expect(host.querySelector('canvas')?.hidden).toBe(true);
 });
 it('reads bounded page text only on request, escapes markup and never substitutes for unvisited pages',async()=>{
  const readText=vi.fn(async()=>'<a href="https://outside.invalid">literal</a>');doc.getPage=vi.fn(async()=>({...page(),readText}));
  await mount();expect(readText).not.toHaveBeenCalled();await click('Read page text');
  expect(host.querySelector('pre')?.textContent).toBe('<a href="https://outside.invalid">literal</a>');expect(host.querySelector('a')).toBeNull();expect(ready).not.toHaveBeenCalledWith(true);
  expect(button('Hide page text').getAttribute('aria-expanded')).toBe('true');await click('Next PDF page');expect(host.querySelector('pre')).toBeNull();
 });
 it('fences late supplemental text after source replacement and aborts the old read',async()=>{
  let release!:(text:string)=>void,captured:AbortSignal|undefined;doc.getPage=vi.fn(async()=>({...page(),readText:(signal:AbortSignal)=>{captured=signal;return new Promise<string>(resolve=>{release=resolve;});}}));
  await mount();await click('Read page text');vi.mocked(openPrivatePdf).mockRejectedValueOnce(new Error('New source denied'));await mount(new Uint8Array(14),{...metadata,byte_length:14});
  expect(captured?.aborted).toBe(true);await act(async()=>release('old private text'));expect(host.textContent).not.toContain('old private text');expect(host.querySelector('pre')).toBeNull();
 });
 it('keeps valid vector Type 3 glyphs but rejects null images inside glyph lists and recursive fonts',async()=>{
  const ops={paintImageXObject:85,paintImageXObjectRepeat:88,setFont:37};let glyph={fnArray:[85],argsArray:[['g_image']]};
  const font={isType3Font:true,charProcOperatorList:{A:glyph}},p={getOperatorList:async()=>({fnArray:[37],argsArray:[['g_font',12]]}),objs:{get:()=>null},commonObjs:{get:(id:string):unknown=>id==='g_font'?font:null}};
  await expect(requireRenderedPdfImages(p,ops)).rejects.toThrow('image could not be decoded');
  glyph.fnArray=[];glyph.argsArray=[];await expect(requireRenderedPdfImages(p,ops)).resolves.toBeUndefined();
  font.charProcOperatorList.A={fnArray:[37],argsArray:[['g_font']]};await expect(requireRenderedPdfImages(p,ops)).rejects.toThrow('Recursive');
 });
 it('checks nested tiling pattern images and rejects missing font objects',async()=>{
  const ops={paintImageXObject:85,paintImageXObjectRepeat:88,setFont:37},nested={fnArray:[85],argsArray:[['image']]};
  const p={getOperatorList:async()=>({fnArray:[55],argsArray:[['TilingPattern',null,nested]]}),objs:{get:()=>null as unknown},commonObjs:{get:()=>null as unknown}};
  await expect(requireRenderedPdfImages(p,ops)).rejects.toThrow('image could not be decoded');p.objs.get=()=>({data:new Uint8Array(1)});
  await expect(requireRenderedPdfImages(p,ops)).resolves.toBeUndefined();
  const missing={...p,getOperatorList:async()=>({fnArray:[37],argsArray:[['font',12]]})};await expect(requireRenderedPdfImages(missing,ops)).rejects.toThrow('font could not be rendered');
 });
 it('bounds raster dimensions and CSS extent at every allowed zoom without stretching a narrow fit',()=>{
  for(const [w,h] of [[612,792],[14400,14400],[1,14400]])for(const zoom of [1,1.5,2,4]){
   const layout=privatePdfLayout(w,h,304,10,zoom);expect(layout.pixelWidth*layout.pixelHeight).toBeLessThanOrEqual(4_000_000);expect(Math.max(layout.pixelWidth,layout.pixelHeight)).toBeLessThanOrEqual(4096);expect(Math.max(layout.cssWidth,layout.cssHeight)).toBeLessThanOrEqual(8192);
  }
  expect(privatePdfLayout(600,800,180,1).cssWidth).toBe(180);expect(()=>privatePdfLayout(600,800,300,1,4.5)).toThrow();expect(()=>privatePdfLayout(600,800,0,1)).toThrow();
 });
 it('bounds text chunks and cancels stalled extraction without returning partial text',async()=>{
  let cancelled=0;const over=new ReadableStream<{items:unknown[]}>({start(c){c.enqueue({items:Array.from({length:4097},()=>({str:'x'}))});},cancel(){cancelled++;}});
  await expect(readPrivatePdfText(over,new AbortController().signal)).rejects.toThrow('limit');expect(cancelled).toBe(1);
  const huge=new ReadableStream<{items:unknown[]}>({start(c){c.enqueue({items:Array.from({length:9},()=>({str:'x'.repeat(4096)}))});},cancel(){cancelled++;}});
  await expect(readPrivatePdfText(huge,new AbortController().signal)).rejects.toThrow('limit');expect(cancelled).toBe(2);
  const controller=new AbortController(),held=new ReadableStream<{items:unknown[]}>({pull(){return new Promise(()=>{});},cancel(){cancelled++;}}),pending=readPrivatePdfText(held,controller.signal);
  const denied=expect(pending).rejects.toThrow();controller.abort();await denied;expect(cancelled).toBe(3);
 });

 it('bounds canvas memory and rejects absurd dimensions',()=>{for(const [w,h] of [[600,800],[14400,14400],[1,14400]]){const scale=privatePdfScale(w,h,10000,10);expect(w*h*scale*scale).toBeLessThanOrEqual(4_000_001);expect(Math.max(w,h)*scale).toBeLessThanOrEqual(4096);}expect(()=>privatePdfScale(0,600,600,1)).toThrow();expect(()=>privatePdfScale(Infinity,600,600,1)).toThrow();expect(()=>privatePdfScale(14401,600,600,1)).toThrow();});
});

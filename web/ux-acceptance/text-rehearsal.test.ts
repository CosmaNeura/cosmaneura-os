import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {installTextRehearsal} from './text-rehearsal';

let root:HTMLDivElement,stop=()=>{};
const frames:FrameRequestCallback[]=[];
beforeEach(()=>{
  frames.length=0;history.replaceState(null,'','/');
  vi.stubGlobal('requestAnimationFrame',(callback:FrameRequestCallback)=>{frames.push(callback);return frames.length;});
  vi.stubGlobal('cancelAnimationFrame',vi.fn());
  root=document.createElement('div');document.body.append(root);
  root.innerHTML='<main class="team-workspace" style="font-size:12px;line-height:18px;width:320px"><p style="font-size:16px;line-height:24px">Invented long visit label</p><button style="font-size:14px;line-height:20px;min-height:44px;width:120px;padding:4px">Open details</button></main>';
});
afterEach(()=>{stop();stop=()=>{};root.remove();history.replaceState(null,'','/');vi.unstubAllGlobals();});
async function paint(){await Promise.resolve();for(const callback of frames.splice(0))callback(0);await Promise.resolve();}

it('leaves the normal rehearsal untouched unless 200 percent text is requested',async()=>{
  const before=root.innerHTML;stop=installTextRehearsal(root);await paint();
  expect(root.innerHTML).toBe(before);expect(root.dataset.textScale).toBeUndefined();expect(frames).toHaveLength(0);
});
it('doubles text without zoom or control scaling and does not compound after new content or resize',async()=>{
  history.replaceState(null,'','/?text-size=200');stop=installTextRehearsal(root);await paint();
  const main=root.querySelector('main')!,paragraph=root.querySelector('p')!,button=root.querySelector('button')!;
  expect(main.style.fontSize).toBe('24px');expect(paragraph.style.fontSize).toBe('32px');expect(paragraph.style.lineHeight).toBe('48px');
  expect(button.style.fontSize).toBe('28px');expect(button.style.minHeight).toBe('44px');expect(button.style.width).toBe('120px');expect(button.style.padding).toBe('4px');
  expect(main.style.width).toBe('320px');expect(main.style.transform).toBe('');expect(main.style.getPropertyValue('zoom')).toBe('');
  const added=document.createElement('span');added.style.fontSize='11px';added.style.lineHeight='16px';added.textContent='A newly opened task';paragraph.append(added);await paint();
  expect(added.style.fontSize).toBe('22px');expect(added.style.lineHeight).toBe('32px');expect(paragraph.style.fontSize).toBe('32px');
  window.dispatchEvent(new Event('resize'));await paint();
  expect(main.style.fontSize).toBe('24px');expect(added.style.fontSize).toBe('22px');expect(button.style.width).toBe('120px');expect(root.dataset.textScale).toBe('200');
});

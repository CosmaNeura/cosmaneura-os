// Isolated UI controls for persona agents when the desktop browser connector is unavailable.
// JSON lines on stdin; observations are accessibility snapshots, never application internals.
import {chromium} from '@playwright/test';
import {createInterface} from 'node:readline';
import {mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
const output=process.argv[2];
if(!output)throw new Error('Supply a local report directory.');
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1280,height:900}});
const origins=new Set(['http://127.0.0.1:5188','http://127.0.0.1:5187']);
await context.route('**/*',route=>origins.has(new URL(route.request().url()).origin)?route.continue():route.abort());
const pages={encounter:await context.newPage(),connections:await context.newPage()};
await pages.encounter.goto('http://127.0.0.1:5188/');
await pages.connections.goto('http://127.0.0.1:5187/');
let page=pages.encounter;
const snapshot=()=>page.locator('body').ariaSnapshot();
const locator=cmd=>{
  let target=cmd.textControl?page.getByText(cmd.textControl,{exact:true}):cmd.label?page.getByLabel(cmd.label,{exact:true}):page.getByRole(cmd.role??'button',{name:cmd.name,exact:true});
  if(cmd.index!==undefined){if(!Number.isInteger(cmd.index)||cmd.index<0||cmd.index>50)throw new Error('Use a visible zero-based occurrence.');target=target.nth(cmd.index);}
  return target;
};
console.log(JSON.stringify({ready:true,surface:'encounter',snapshot:await snapshot()}));
try {
  for await(const line of createInterface({input:process.stdin})){
    try {
      const cmd=JSON.parse(line);
      switch(cmd.action){
        case 'surface':if(!Object.hasOwn(pages,cmd.name))throw new Error('Use encounter or connections.');page=pages[cmd.name];break;
        case 'click':await locator(cmd).click({timeout:5000});break;
        case 'fill':await locator(cmd).fill(cmd.text,{timeout:5000});break;
        case 'check':await locator(cmd).setChecked(cmd.checked??true,{timeout:5000});break;
        case 'select':await locator(cmd).selectOption({label:cmd.option},{timeout:5000});break;
        case 'key':await locator(cmd).press(cmd.key,{timeout:5000});break;
        case 'scroll':await page.mouse.move(cmd.x??1050,cmd.y??700);await page.mouse.wheel(0,Math.max(-900,Math.min(900,cmd.dy??500)));break;
        case 'reload':await page.reload();break;
        case 'snapshot':break;
        case 'screenshot':{
          if(!/^[a-z0-9_-]+\.png$/.test(cmd.file))throw new Error('Use a simple PNG filename.');
          const path=resolve(output,cmd.file);await page.screenshot({path,fullPage:cmd.fullPage??false});console.log(JSON.stringify({screenshot:path}));break;
        }
        case 'close':await browser.close();process.exit(0);
        default:throw new Error('Unknown UI action.');
      }
      console.log(JSON.stringify({url:page.url(),snapshot:await snapshot()}));
    }catch(error){console.log(JSON.stringify({error:error.message,snapshot:await snapshot()}));}
  }
}finally{await browser.close();}

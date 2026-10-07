import assert from 'node:assert/strict';
import test from 'node:test';
import {desktopMenuTemplate,desktopUpdateDetail} from './desktop-update-guidance.mjs';
test('offers manual update guidance with source version and preserves normal quit handling',async()=>{
  const config={appVersion:'0.1.80',buildNumber:'1040',sourceProvenance:{commit:'a'.repeat(40)}};
  let detail,quit=0;
  const menu=desktopMenuTemplate({app:{quit:()=>quit++},dialog:{showMessageBox:async options=>{detail=options;return{response:0};}},config});
  await menu[0].submenu.find(item=>item.label==='Update CosmaBot…').click();
  assert.match(detail.detail,/0\.1\.80 \(build 1040\)/);assert.match(detail.detail,/aaaaaaaaaaaa/);
  assert.match(detail.detail,/Automatic downloads are not available/);
  menu[0].submenu.find(item=>item.label==='Quit CosmaBot').click();assert.equal(quit,1);
  assert.match(desktopUpdateDetail({sourceProvenance:{commit:'invalid'}}),/Source not recorded/);
});

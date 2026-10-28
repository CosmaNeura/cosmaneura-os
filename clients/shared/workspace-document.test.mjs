import assert from 'node:assert/strict';
import test from 'node:test';
import {isPackagedWorkspaceDocument,PACKAGED_WORKSPACE_DOCUMENT as entry} from './workspace-document.mjs';

test('navigation fragments retain the exact packaged document',()=>{
  for(const fragment of ['', '#', '#cosmas/home', '#cosmas/settings',
    '#cosmas/notebook/00000000-0000-4000-8000-000000000084?helper=chief&material=Sources',
    '#google-connected', '#https://outside.invalid']){
    assert.equal(isPackagedWorkspaceDocument(entry+fragment),true);
  }
});

test('fragments never relax the canonical document, origin, credentials, port, query or path',()=>{
  for(const value of [null,{},'', 'https://cosmas/index.html', 'app://other/index.html',
    'app://cosmas.evil.invalid/index.html', 'app://user@cosmas/index.html', 'app://cosmas:443/index.html',
    'app://cosmas/index.html?owner=other', 'app://cosmas/index.html/','app://cosmas/other.html',
    'app://cosmas/a/../index.html','app://cosmas/%69ndex.html','app://cosmas//index.html',
    'app://cosmas\\index.html','APP://cosmas/index.html','app://Cosmas/index.html',
    ' app://cosmas/index.html','app://cosmas/index.html\n']){
    assert.equal(isPackagedWorkspaceDocument(value),false);
    if(typeof value==='string')assert.equal(isPackagedWorkspaceDocument(value+'#cosmas/home'),false);
  }
});

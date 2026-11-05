import {describe,expect,it} from 'vitest';
import {showDemoLabels} from './demo-labels';
describe('showDemoLabels',()=>{
  it('hides demo labels only for a hosted build with real practice data',()=>{
    expect(showDemoLabels({VITE_WORKSPACE_HOSTED_ENABLED:'true',VITE_WORKSPACE_DATA_MODE:'authorized_beta'})).toBe(false);
  });
  it('keeps demo labels for synthetic, local and misconfigured builds',()=>{
    expect(showDemoLabels({VITE_WORKSPACE_HOSTED_ENABLED:'true',VITE_WORKSPACE_DATA_MODE:'synthetic'})).toBe(true);
    expect(showDemoLabels({})).toBe(true);
    expect(showDemoLabels({VITE_WORKSPACE_DATA_MODE:'authorized_beta'})).toBe(true);
    expect(showDemoLabels({VITE_WORKSPACE_HOSTED_ENABLED:'false',VITE_WORKSPACE_DATA_MODE:'authorized_beta'})).toBe(true);
  });
});
describe('showDemoLabels for registered native practices',()=>{
  it('hides demo labels for a real-data native practice and keeps them for synthetic or unknown',()=>{
    expect(showDemoLabels({},()=> 'authorized_beta')).toBe(false);
    expect(showDemoLabels({},()=> 'synthetic')).toBe(true);
    expect(showDemoLabels({},()=> undefined)).toBe(true);
  });
});

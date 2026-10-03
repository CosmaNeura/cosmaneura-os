import {expect,it} from 'vitest';
import {PRIVATE_PDF_EXECUTION_POLICY} from './private-pdf';
it('keeps private PDF active features disabled and immutable',()=>{
  expect(PRIVATE_PDF_EXECUTION_POLICY).toEqual({isEvalSupported:false,enableScripting:false,enableXfa:false,useWasm:false});
  expect(Object.isFrozen(PRIVATE_PDF_EXECUTION_POLICY)).toBe(true);
});

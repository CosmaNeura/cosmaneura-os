import {expect,it} from 'vitest';
import {nativeRehearsal} from './native-rehearsal';

it.each([
  'capacitor://localhost/',
  'capacitor://localhost/index.html#cosmas/home',
])('uses native keyboard behavior in the composed queryless rehearsal: %s',url=>{
  expect(nativeRehearsal(new URL(url),true)).toBe(true);
});

it.each([
  'http://127.0.0.1:5187/',
  'https://localhost/',
  'capacitor://other-host/',
  'capacitor://localhost.example/',
  'capacitor://localhost:5187/',
  'capacitor://invented-user@localhost/',
  'capacitor://:invented-password@localhost/',
])('does not silently select native behavior in another host: %s',url=>{
  expect(nativeRehearsal(new URL(url),true)).toBe(false);
});

it('does not automatically select native behavior inside an embedded document',()=>{
  expect(nativeRehearsal(new URL('capacitor://localhost/'),false)).toBe(false);
});

it.each([true,false])('retains the explicit browser native-chat rehearsal (top level: %s)',topLevel=>{
  expect(nativeRehearsal(new URL('http://127.0.0.1:5187/?native-chat=1'),topLevel)).toBe(true);
});

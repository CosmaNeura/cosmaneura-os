import {beforeEach,vi} from 'vitest';

// Node 25+ installs a configurable global localStorage that stays undefined
// unless --localstorage-file is set. That getter shadows jsdom, so Storage
// tests cannot persist. Replace it with an in-memory Storage before imports.
function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() { return data.size; },
    clear() { data.clear(); },
    getItem(key) { return data.has(String(key)) ? data.get(String(key))! : null; },
    key(index) { return [...data.keys()][index] ?? null; },
    removeItem(key) { data.delete(String(key)); },
    setItem(key, value) { data.set(String(key), String(value)); },
  };
}
function storageWorks(name: 'localStorage' | 'sessionStorage') {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
  if (!descriptor) return false;
  if (descriptor.value && typeof descriptor.value.getItem === 'function') return true;
  if (typeof descriptor.get !== 'function') return false;
  const emit = process.emitWarning;
  process.emitWarning = ((warning: unknown, ...rest: unknown[]) => {
    if (String(warning).includes('localStorage is not available') || String(warning).includes('sessionStorage is not available')) return;
    return (emit as (...args: unknown[]) => void).call(process, warning, ...rest);
  }) as typeof process.emitWarning;
  try {
    const value: unknown = descriptor.get.call(globalThis);
    return !!value && typeof (value as Storage).getItem === 'function';
  } catch {
    return false;
  } finally {
    process.emitWarning = emit;
  }
}
function installStorage(name: 'localStorage' | 'sessionStorage') {
  if (storageWorks(name)) return;
  const storage = memoryStorage();
  Object.defineProperty(globalThis, name, {configurable: true, enumerable: true, writable: true, value: storage});
  if (typeof window !== 'undefined') {
    try { Object.defineProperty(window, name, {configurable: true, enumerable: true, writable: true, value: storage}); }
    catch { /* jsdom already exposed a working Storage */ }
  }
}
installStorage('localStorage');
installStorage('sessionStorage');

// Each case starts with a fresh browser route; deliberate remounts within a
// case retain their URL unless that fixture explicitly navigates Home.
beforeEach(()=>{if(typeof window!=='undefined'&&window.history&&typeof window.history.replaceState==='function'&&window.location){window.history.replaceState(null,'',window.location.pathname+window.location.search);window.scrollTo=vi.fn();}});

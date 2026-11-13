import {describe, expect, it, vi} from 'vitest';
import * as shared from '../../clients/shared/operational-native-identity.mjs';

const {readFileSync} = await vi.importActual<{readFileSync: (path: string, encoding: 'utf8') => string}>('node:fs');
const {resolve} = await vi.importActual<{resolve: (...parts: string[]) => string}>('node:path');
const nodeProcess = await vi.importActual<{cwd: () => string}>('node:process');

const declarationPath = resolve(nodeProcess.cwd(), '../clients/shared/operational-native-identity.d.mts');

describe('operational-native-identity.d.mts parity', () => {
  it('pins every export const literal and the export-name set to the runtime module', () => {
    const declaration = readFileSync(declarationPath, 'utf8');
    const literals = [...declaration.matchAll(/export const ([A-Z0-9_]+):\s*"([^"]+)";/g)];
    expect(literals.length).toBeGreaterThanOrEqual(7);
    for (const [, name, literal] of literals) {
      expect(shared[name as keyof typeof shared], name).toBe(literal);
    }
    const declaredExports = new Set<string>();
    for (const match of declaration.matchAll(/export (?:const|function|type) ([A-Za-z0-9_]+)/g)) {
      declaredExports.add(match[1]);
    }
    for (const name of Object.keys(shared)) {
      expect(declaredExports.has(name), `missing .d.mts export for ${name}`).toBe(true);
    }
  });
});

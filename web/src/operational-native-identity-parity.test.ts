import {describe, expect, it, vi} from 'vitest';
import * as shared from '../../clients/shared/operational-native-identity.mjs';
import {
  OPERATIONAL_NATIVE_PROFILE,
  PRODUCTION_API_ORIGIN,
  PRODUCTION_NATIVE_PROFILE,
  STAGING_NATIVE_PROFILE,
  validateOperationalNativeIdentity,
} from '../../clients/shared/operational-native-identity.mjs';

const {readFileSync} = await vi.importActual<{readFileSync: (path: string, encoding: 'utf8') => string}>('node:fs');
const {resolve} = await vi.importActual<{resolve: (...parts: string[]) => string}>('node:path');
const nodeProcess = await vi.importActual<{cwd: () => string}>('node:process');

const declarationPath = resolve(nodeProcess.cwd(), '../clients/shared/operational-native-identity.d.mts');

function liveKey(host: string): string {
  const bytes = new TextEncoder().encode(host + '$');
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return 'pk_live_' + btoa(binary);
}

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

describe('PRODUCTION_API_ORIGIN identity refusal', () => {
  it('refuses a non-production identity that carries PRODUCTION_API_ORIGIN', () => {
    const betaWithProductionOrigin = {
      version: 1 as const,
      profile: OPERATIONAL_NATIVE_PROFILE,
      client: 'desktop' as const,
      apiOrigin: PRODUCTION_API_ORIGIN,
      frontendOrigin: 'https://clerk.cosmas.ai',
      publishableKey: liveKey('clerk.cosmas.ai'),
      organizationId: 'org_invented_beta',
      audience: 'cosmas-os-beta-api',
    };
    expect(() =>
      validateOperationalNativeIdentity(betaWithProductionOrigin, 'desktop', PRODUCTION_API_ORIGIN),
    ).toThrow(/incomplete or inconsistent/i);

    const stagingWithProductionOrigin = {
      ...betaWithProductionOrigin,
      profile: STAGING_NATIVE_PROFILE,
      frontendOrigin: 'https://clerk.staging.cosmas.ai',
      publishableKey: liveKey('clerk.staging.cosmas.ai'),
    };
    expect(() =>
      validateOperationalNativeIdentity(stagingWithProductionOrigin, 'desktop', PRODUCTION_API_ORIGIN),
    ).toThrow(/incomplete or inconsistent/i);

    const production = {
      version: 1 as const,
      profile: PRODUCTION_NATIVE_PROFILE,
      client: 'desktop' as const,
      apiOrigin: PRODUCTION_API_ORIGIN,
      frontendOrigin: 'https://clerk.beta.cosmas.ai',
      publishableKey: liveKey('clerk.beta.cosmas.ai'),
      organizationId: 'org_invented_beta',
      audience: 'cosmas-os-beta-api',
    };
    expect(validateOperationalNativeIdentity(production, 'desktop', PRODUCTION_API_ORIGIN)).toEqual(production);
  });
});

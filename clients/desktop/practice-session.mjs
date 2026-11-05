/**
 * Main-process CosmasDesktopPractice host (Electron).
 * Fake/local L0 enrollment works without a signed Swift helper.
 * Reviewed production Infos bind the HTTPS enrollment origin but fail closed on
 * Clerk account-realm / Open Chief until a signed practice helper is available.
 * Tokens stay in this process; preload never exposes getToken.
 */

import {randomUUID} from 'node:crypto';
import {createFakePracticeAccountWire} from './practice-fake-wire.mjs';
import {createHttpsPracticeAccountWire} from './practice-https-wire.mjs';
import {
  isProductionNativePracticeInfos,
  productionPracticeHelperRequiredMessage,
  validateNativePracticeInfos,
} from './practice-infos-config.mjs';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const CONTRACT = 'cosmabot.native-practice-connection.v1';
const unavailable = () => new Error('Desktop practice connection unavailable');
const productionBlocked = () => new Error(productionPracticeHelperRequiredMessage());
function desktopSnapshot(identity, practiceMeta) {
  const stamp = Math.floor(Date.now() / 1000);
  const issuer = 'https://invented.clerk.accounts.dev';
  const frontendHost = issuer.replace('https://', '');
  return Object.freeze({
    contract_version: 'cosmabot.native-active-workspace.v1',
    revision: randomUUID(),
    profile: Object.freeze({
      contract_version: 'cosmas-native-workspace-profile.v1',
      client: 'desktop',
      nonce: randomUUID(),
      native_origin: 'app://cosmas',
      data_mode: 'synthetic',
      nativeIdentity: Object.freeze({
        version: 1, profile: 'operational-staging-v1', client: 'desktop',
        apiOrigin: `https://api.${practiceMeta.WORKSPACE_HOST}`,
        publishableKey: 'pk_test_' + Buffer.from(`${frontendHost}$`).toString('base64'),
        frontendOrigin: issuer, organizationId: practiceMeta.ORG_ID, audience: '',
      }),
      session: Object.freeze({
        issuer, subject: identity.userId, session_id: identity.sessionId,
      }),
      practice: Object.freeze({
        practice_id: practiceMeta.PRACTICE_ID, box_id: practiceMeta.BOX_ID,
      }),
      workspace: Object.freeze({
        url: `https://${practiceMeta.WORKSPACE_HOST}/chief`,
        source_commit: '1'.repeat(40), image_sha256: '2'.repeat(64),
        workspace_proof_sha256: '3'.repeat(64), member_proof_sha256: '4'.repeat(64),
        native_qualification_sha256: '5'.repeat(64),
      }),
      issued_at: stamp, expires_at: stamp + 120,
    }),
  });
}

/** Fake JWT shape accepted by parseNativeToken — three dotted segments, no real crypto. */
function fakeToken() {
  return 'eyJhbGciOiJub25lIn0.eyJzdWIiOiJpbnZlbnRlZCJ9.invented';
}

/**
 * @param {{
 *   enabled?: boolean,
 *   infos?: object,
 *   signedPracticeHelperAvailable?: boolean,
 *   wire?: {enrollmentRequest: Function},
 *   admitWorkspace?: (snapshot: object) => Promise<void>,
 * }} options
 */
export async function createDesktopPracticeSession({
  enabled = false,
  infos = undefined,
  signedPracticeHelperAvailable = false,
  wire,
  admitWorkspace = async () => {},
} = {}) {
  const closedInfos = infos === undefined ? null : validateNativePracticeInfos(infos);
  const productionInfos = closedInfos ? isProductionNativePracticeInfos(closedInfos) : false;
  if (closedInfos && !closedInfos.enabled) {
    throw new Error('Native practice Infos is disabled; omit Connect practice instead of wiring a dark host.');
  }
  if (productionInfos && wire !== undefined && 'PRACTICE_ID' in wire) {
    throw new Error('Production Infos cannot use a fake/local practice enrollment wire.');
  }
  const activeWire = wire ?? (closedInfos
    ? createHttpsPracticeAccountWire({infos: closedInfos})
    : createFakePracticeAccountWire());  // Production Infos may expose Connect so /native/config can prove the Infos path,
  // but account/Open Chief stay fail-closed without the signed helper.
  const accountRealmReady = !productionInfos || signedPracticeHelperAvailable === true;
  let phase = enabled ? 'signedOut' : 'unavailable';
  let revision = randomUUID();
  let identity = null;
  let disposed = false;
  const listeners = new Set();
  function view() {
    return Object.freeze({
      phase, revision,
      identity: identity ? Object.freeze({...identity}) : null,
    });
  }

  function change(nextPhase, nextIdentity = null) {
    if (disposed) return;
    const same = phase === nextPhase &&
      identity?.userId === nextIdentity?.userId &&
      identity?.sessionId === nextIdentity?.sessionId;
    if (same && nextPhase !== 'signingIn') return;
    phase = nextPhase;
    identity = nextIdentity;
    revision = randomUUID();
    const state = view();
    for (const listener of listeners) {
      try { listener(state); } catch { /* No raw callback errors. */ }
    }
  }

  function expectRevision(expected) {
    if (!enabled || disposed || typeof expected !== 'string' || !UUID.test(expected) || expected !== revision) {
      throw unavailable();
    }
  }

  async function capabilities() {
    if (disposed) throw unavailable();
    return Object.freeze({
      contract_version: CONTRACT,
      available: enabled === true,
      enrollment_available: enabled === true,
    });
  }

  async function accountStatus() {
    if (disposed) throw unavailable();
    if (!enabled) {
      change('unavailable');
      return view();
    }
    return view();
  }

  async function beginAccountSignIn() {
    if (!enabled || disposed || phase === 'signingIn') throw unavailable();
    if (!accountRealmReady) throw productionBlocked();
    change('signingIn');
    // Local fake account — no Clerk helper reconfigure in the L0 slice.
    const next = Object.freeze({
      userId: 'user_invented_desktop',
      sessionId: 'sess_invented_desktop',
      email: 'owner@example.invalid',
      displayName: 'Invented Desktop Owner',
    });
    change('accountReady', next);
    return view();
  }

  async function accountToken({expectedRevision} = {}) {
    expectRevision(expectedRevision);
    if (!accountRealmReady) throw productionBlocked();
    if (phase !== 'accountReady' || !identity) throw unavailable();
    return Object.freeze({token: fakeToken(), revision});
  }

  async function enrollmentRequest(options = {}) {
    expectRevision(options.expectedRevision);
    if (options.operation !== 'config' && (phase !== 'accountReady' || !identity)) throw unavailable();
    if (options.operation !== 'config' && !accountRealmReady) throw productionBlocked();
    const ops = new Set([
      'config', 'status', 'practices', 'selectPractice', 'profile', 'practice', 'join', 'document',
      'accept', 'receipt', 'quote', 'checkout', 'recover', 'confirmWorkspace', 'invitation', 'portal',
    ]);
    if (!ops.has(options.operation)) throw unavailable();
    if (options.idempotencyKey !== undefined &&
        (typeof options.idempotencyKey !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(options.idempotencyKey))) {
      throw unavailable();
    }
    return activeWire.enrollmentRequest(options.operation, options.body, {
      idempotencyKey: options.idempotencyKey,
    });
  }
  async function openEnrollmentDestination({expectedRevision, destination} = {}) {
    expectRevision(expectedRevision);
    if (phase !== 'accountReady' || !['checkout', 'portal'].includes(destination)) throw unavailable();
    // Fake wire has no Stripe URL; report opened so UI fails closed on missing billing later.
    return Object.freeze({status: 'opened'});
  }

  async function openCheckout(options = {}) {
    // Required by Mac detector; production UI uses openEnrollmentDestination.
    return openEnrollmentDestination({
      expectedRevision: options.expectedRevision, destination: 'checkout',
    });
  }

  async function activatePracticeOrganization({expectedRevision} = {}) {
    expectRevision(expectedRevision);
    if (!accountRealmReady) throw productionBlocked();
    if (phase !== 'accountReady' || !identity) throw unavailable();
    return Object.freeze({token: fakeToken(), revision});
  }

  async function activateRegisteredPractice({expectedRevision} = {}) {
    expectRevision(expectedRevision);
    if (!accountRealmReady) throw productionBlocked();
    if (phase !== 'accountReady' || !identity) throw unavailable();
    if (productionInfos || !('PRACTICE_ID' in activeWire)) throw productionBlocked();
    const snapshot = desktopSnapshot(identity, activeWire);
    await admitWorkspace(snapshot);
    return snapshot;
  }
  async function returnToBeta({expectedRevision} = {}) {
    expectRevision(expectedRevision);
    change('signedOut');
  }

  async function signOut({expectedRevision} = {}) {
    expectRevision(expectedRevision);
    change('signedOut');
    return view();
  }

  function subscribe(listener) {
    if (typeof listener !== 'function' || listeners.size >= 32) throw unavailable();
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }

  function close() {
    disposed = true;
    listeners.clear();
    phase = 'unavailable';
    identity = null;
  }

  return Object.freeze({
    capabilities, accountStatus, beginAccountSignIn, accountToken, enrollmentRequest,
    openCheckout, openEnrollmentDestination, activatePracticeOrganization,
    activateRegisteredPractice, returnToBeta, signOut, subscribe, close, snapshot: view,
  });
}

/**
 * Local/fake enrollment wire for Mac CosmasDesktopPractice (L0).
 * Returns closed synthetic enrollment.v1 shapes with Origin app://cosmas.
 * Never talks to a network or reads credentials from the renderer.
 */

const ENROLLMENT_CONTRACT = 'enrollment.v1';
const BAA = Object.freeze({
  doc_id: 'CN-BAA-CUST-CW', version: '2.3',
  sha256: '9bdc110b6b2ffcc9f5e7aee653af499357d2f35dccf43c57d8bbcf70094ed34e',
  pdf_url: 'https://cosmaneura.com/baa-v2-3.pdf',
});
const PRACTICE_ID = '10000000-0000-4000-8000-000000000001';
const BOX_ID = '10000000-0000-4000-8000-000000000003';
const ORG_ID = 'org_invented_desktop';
const WORKSPACE_HOST = 'invented.staging.cosmas.ai';

const seatPolicy = 'All humans consume a purchased seat; paused users retain their seat until removed.';

export function createFakePracticeAccountWire({nativeOrigin = 'app://cosmas'} = {}) {
  if (nativeOrigin !== 'app://cosmas') throw new Error('Desktop practice wire requires Origin app://cosmas');
  let revision = 1;

  function configBody() {
    return {
      contract_version: ENROLLMENT_CONTRACT, enabled: true, data_mode: 'synthetic',
      auth_configured: true, clerk_publishable_key: 'pk_test_invented',
      auth_methods: ['google', 'microsoft', 'password'], billing_configured: true,
      activation_available: true, checkout_recovery_available: false, production_qualified: false,
      blockers: [], allowed_workspace_origins: [`https://${WORKSPACE_HOST}`],
      workspace_origin_policy: 'synthetic-practice-uuid-staging-v1', baa: {...BAA},
      pricing: {
        currency: 'usd', interval: 'month', first_human_cents: 30000, additional_human_cents: 10000,
        max_self_serve_humans: 10, trial_days: 14, seat_policy: seatPolicy,
      },
      // Host-only fields stripped by validateNativeEnrollmentConfig.
      native_account: {
        issuer: 'https://invented.clerk.accounts.dev', audience: '',
        session_policy: 'synthetic-desktop-v1', native_origin: nativeOrigin,
      },
      workspace_confirmation_configured: true,
    };
  }

  function readyStatus() {
    return {
      contract_version: ENROLLMENT_CONTRACT, revision, stage: 'ready',
      profile: {display_name: 'Invented Desktop Owner', title: 'Owner', email: 'owner@example.invalid'},
      practice: {
        id: PRACTICE_ID, legal_name: 'Invented Legal Practice', display_name: 'Invented Practice',
        address_line1: '123 Invented Street', address_line2: '', city: 'Invented City', region: 'NY',
        postal_code: '10001', country: 'US', administrative_email: 'office@example.invalid',
        human_seats: 1, role: 'owner', covered_entity: true, can_sign: true,
      },
      agreement: {
        accepted: true, doc_id: BAA.doc_id, version: BAA.version, sha256: BAA.sha256,
        receipt_id: '10000000-0000-4000-8000-000000000002',
      },
      quote: {
        currency: 'usd', interval: 'month', human_seats: 1, monthly_total_cents: 30000,
        due_today_cents: 0, trial_days: 14, self_serve: true,
      },
      billing: {
        status: 'trialing', trial_ends_at: '2026-11-15T12:00:00Z',
        first_charge_at: '2026-11-15T12:00:00Z', cancel_at_period_end: false,
        payment_action_required: false,
      },
      workspace: {
        status: 'ready', url: `https://${WORKSPACE_HOST}/chief`,
        organization_id: ORG_ID, box_id: BOX_ID, confirmation_available: true,
      },
      action_required: null,
    };
  }

  async function enrollmentRequest(operation) {
    switch (operation) {
      case 'config':
        return {status: 200, body: configBody()};
      case 'status':
      case 'confirmWorkspace':
        return {status: 200, body: readyStatus()};
      case 'practices':
        return {
          status: 200,
          body: {
            active_practice_id: PRACTICE_ID,
            practices: [{
              id: PRACTICE_ID, legal_name: 'Invented Legal Practice', display_name: 'Invented Practice',
              role: 'owner', workspace_status: 'ready',
            }],
          },
        };
      case 'selectPractice':
        revision += 1;
        return {status: 200, body: readyStatus()};
      case 'document':
        return {
          status: 200,
          body: {
            ...BAA,
            html: '<article><h1>CN-BAA-CUST-CW v2.3</h1><p>Invented render fixture only.</p></article>',
          },
        };
      case 'quote':
        return {
          status: 200,
          body: {
            currency: 'usd', interval: 'month', human_seats: 1, monthly_total_cents: 30000,
            due_today_cents: 0, trial_days: 14, self_serve: true,
          },
        };
      case 'checkout':
      case 'portal':
        return {
          status: 200,
          body: {url: null, status: 'pending', enrollment: readyStatus()},
        };
      case 'profile':
      case 'practice':
      case 'join':
      case 'accept':
      case 'receipt':
      case 'recover':
      case 'invitation':
        revision += 1;
        return {status: 200, body: readyStatus()};
      default:
        return {status: 404, body: {detail: {code: 'enrollment_unavailable'}}};
    }
  }

  return Object.freeze({
    PRACTICE_ID, BOX_ID, ORG_ID, WORKSPACE_HOST, enrollmentRequest,
  });
}

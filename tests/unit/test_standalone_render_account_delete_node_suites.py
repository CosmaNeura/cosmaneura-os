"""CI wrappers for standalone render Node suites that synth-ci would otherwise miss.

Runs in a `python-tests-migrate` backend shard (positional). Missing `node`
raises AssertionError (fail, never skip).

Covers the account-delete staging contract fingerprints, production-review
key-name allowance, and capture/tools DNS/egress pins in:
  infra/standalone/render-capture-tools.test.mjs
  infra/standalone/render-goldens.test.mjs
  infra/standalone/render-beta.test.mjs
  infra/standalone/render.test.mjs
  infra/standalone/account-delete-profile-matrix.test.mjs

Mutation note: dropping a path from NODE_SUITES, or removing the
returncode assertion, lets golden/fingerprint or review-name drift leave CI green.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

NODE_SUITES = (
    "infra/standalone/render-capture-tools.test.mjs",
    "infra/standalone/render-goldens.test.mjs",
    "infra/standalone/render-beta.test.mjs",
    "infra/standalone/render.test.mjs",
    "infra/standalone/account-delete-profile-matrix.test.mjs",
)


def _require_node() -> str:
    found = shutil.which("node")
    if found is None:
        raise AssertionError(
            "node is required for standalone render account-delete Node suites"
        )
    return found


@pytest.mark.parametrize("relative", NODE_SUITES)
def test_standalone_render_account_delete_node_suite(relative: str) -> None:
    node = _require_node()
    path = ROOT / relative
    assert path.is_file(), relative
    result = subprocess.run(
        [node, "--test", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, f"{relative}\n{result.stdout}\n{result.stderr}"


def test_node_suites_tuple_covers_capture_tools_goldens_and_review() -> None:
    """Set pin: dropping a suite from NODE_SUITES fails this assertion."""
    required = {
        "infra/standalone/render-capture-tools.test.mjs",
        "infra/standalone/render-goldens.test.mjs",
        "infra/standalone/render-beta.test.mjs",
        "infra/standalone/render.test.mjs",
        "infra/standalone/account-delete-profile-matrix.test.mjs",
    }
    assert set(NODE_SUITES) >= required


def test_node_render_behaviour_pins_staging_review_and_egress() -> None:
    """Behaviour pins (not source substrings): goldens + beta mapping + egress."""
    node = _require_node()
    script = r"""
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {render, Refused, ACCOUNT_DELETE_ENV_NAME, REVIEW_ACCOUNT_DELETE_HOST_KEY,
  STAGING_ACCOUNT_DELETE_VAULT_SECRET} from './infra/standalone/render.mjs';

const sample=JSON.parse(await readFile('./infra/standalone/invented-host-input.json','utf8'));
const fp=files=>createHash('sha256').update(JSON.stringify(files)).digest('hex');
function liveKey(host){return 'pk_live_'+Buffer.from(`${host}$`).toString('base64');}
function owned(host, extras={}){
  const value=structuredClone(sample);
  value.resource_scope='owned-cosmabot-vm-instance';
  value.web_origin=`https://${host}`; value.api_origin=`https://api.${host}`;
  value.identity.apiOrigin=value.api_origin; value.tls.hostnames=[host,`api.${host}`];
  Object.assign(value.identity, extras.identity||{});
  value.identity_policy=extras.policy||'audience';
  value.beta_features={model:{origin:'https://invented-owned-chief.openai.azure.com',
    endpoint:'https://invented-owned-chief.openai.azure.com/openai/v1',deployment:'gpt-4.1'},
    google:{client_id:'invented-client.apps.googleusercontent.com',
      callback_uri:value.api_origin+'/connections/google/callback',return_origin:value.web_origin}};
  return value;
}

test('owned staging fingerprint and vault mapping',()=>{
  // Match render-goldens owned staging: keep sample identity; only scope/origins/features.
  const value=owned('staging.cosmas.ai');
  const files=render(value);
  assert.equal(fp(files),'a2e8726ce2de6ea44208d8d73b69ac039243884b71e922222ee680ba1a0e8c7f');
  const pe=files['host-preparation.json'].private_environment;
  assert.deepEqual(pe.key_vault_secret_names,{
    [ACCOUNT_DELETE_ENV_NAME]:STAGING_ACCOUNT_DELETE_VAULT_SECRET,
  });
});

test('owned beta review mapping and api.clerk.com egress',()=>{
  const value=owned('beta.cosmas.ai',{identity:{
    profile:'operational-production-v1', audience:'cosmas-os-beta-api',
    frontendOrigin:'https://clerk.beta.cosmas.ai',
    publishableKey:liveKey('clerk.beta.cosmas.ai'),
  }});
  const files=render(value);
  const pe=files['host-preparation.json'].private_environment;
  assert.deepEqual(pe.optional_exact_names,[ACCOUNT_DELETE_ENV_NAME]);
  assert.deepEqual(pe.key_vault_secret_names,{
    [ACCOUNT_DELETE_ENV_NAME]:REVIEW_ACCOUNT_DELETE_HOST_KEY,
  });
  assert.ok(files['network-requirements.json'].api_egress.some(i=>i.hostname==='api.clerk.com'));
});

test('owned beta refuses operational-beta-v1',()=>{
  const value=owned('beta.cosmas.ai',{identity:{
    profile:'operational-beta-v1', audience:'cosmas-os-beta-api',
    frontendOrigin:'https://clerk.beta.cosmas.ai',
    publishableKey:liveKey('clerk.beta.cosmas.ai'),
  }});
  assert.throws(()=>render(value), e=>e instanceof Refused);
});
"""
    path = ROOT / ".tmp-account-delete-behaviour.test.mjs"
    path.write_text(script, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, "--test", str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        path.unlink(missing_ok=True)

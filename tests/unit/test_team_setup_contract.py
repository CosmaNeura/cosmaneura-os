import hashlib
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from cosmas_os.api.team_schemas import PresetBinding, SetupReview, TeamConfiguration
from cosmas_os.application import provider_team as team
from cosmas_os.application import team_setup
from cosmas_os.domain.hashing import payload_hash


def test_legacy_provider_default_and_empty_new_fields_keep_identical_request_digest():
    original={'practice_context':'Direct Primary Care','bots':[
        {'role':role,'name':name,'enabled':True,'response_style':'brief','include_notebook':True,'include_evidence':True}
        for role,name in [('scribe','Scribe'),('visit_prep','Visit Prep'),('follow_up','Follow-up'),('chief','Chief')]]}
    assert team.default_configuration()==original
    changed=deepcopy(original)
    changed['presets']=[]
    for bot in changed['bots']:
        bot['blocked_capabilities']=[]
    assert team.configuration_value(changed)==original
    assert payload_hash({'expected':0,'configuration':team.configuration_value(changed)})==payload_hash({'expected':0,'configuration':original})


@pytest.mark.parametrize('version',[True,'1',0,2])
def test_catalog_binding_versions_are_exact_strict_integers(version):
    with pytest.raises(ValidationError):
        PresetBinding.model_validate({'preset_id':'provider','version':version,'slots':{role:role for role in ('scribe','visit_prep','follow_up','chief')}})
    if version == 2:
        assert SetupReview.model_validate({'catalog_version':version,'configuration_sha256':'a'*64,'prerequisites_sha256':'b'*64}).catalog_version == 2
    else:
        with pytest.raises(ValidationError):
            SetupReview.model_validate({'catalog_version':version,'configuration_sha256':'a'*64,'prerequisites_sha256':'b'*64})


@pytest.mark.parametrize('fault',['unknown_deny','duplicate_deny','unknown_preset','missing_provider','wrong_baseline','surrogate'])
def test_configuration_rejects_ambiguous_or_unbounded_new_authority_fields(fault):
    value=team.default_configuration()
    if fault=='unknown_deny':
        value['bots'][0]['blocked_capabilities']=['send_email']
    elif fault=='duplicate_deny':
        value['bots'][0]['blocked_capabilities']=['model_answer','model_answer']
    elif fault=='surrogate':
        value['bots'][0]['name']='bad\ud800'
    else:
        value['presets']=[{'preset_id':'provider','version':1,'slots':{role:role for role in ('scribe','visit_prep','follow_up','chief')}}]
        if fault=='unknown_preset':
            value['presets'][0]['preset_id']='autonomous_finance'
        if fault=='wrong_baseline':
            value['presets'][0]['slots']['scribe']='visit_prep'
        if fault=='missing_provider':
            value['presets']=[{'preset_id':'practice_manager','version':1,'slots':{'operations':'scribe','membership_billing':'visit_prep','chief':'chief'}}]
    with pytest.raises(ValidationError):
        TeamConfiguration.model_validate(value)


def test_unicode_configuration_hash_is_over_normalized_public_text_not_legacy_ascii_encoding():
    value=team.default_configuration()
    value['bots'][0]['name']='  Résumé 🧑🏽  '
    normal=team.configuration_value(value)
    assert normal['bots'][0]['name']=='Résumé 🧑🏽'
    expected=hashlib.sha256(json.dumps(normal,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    assert team_setup.digest(normal)==expected and expected!=payload_hash(normal)

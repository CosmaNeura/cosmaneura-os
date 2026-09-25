import hashlib
import json

import pytest
from pydantic import ValidationError

from cosmas_os.api.prep_work_schemas import PrepWorkDecision
from cosmas_os.application.prep_work import public_prep_receipt
from cosmas_os.ports.encounter_prep import CorePrepReceipt
from tests.unit.test_encounter_prep import receipt


def test_public_prep_display_omits_bearer_references_and_binds_redacted_content():
    raw=receipt(); secret=raw['sources'][0]['source_ref']; token=secret.removeprefix('intake_')
    raw['sources'][0]['content']='Saved summary — '+secret+' '+token
    raw.pop('snapshot_sha256')
    raw['snapshot_sha256']=hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    value=public_prep_receipt(CorePrepReceipt.model_validate(raw))
    assert secret not in json.dumps(value) and token not in json.dumps(value)
    source=value['sources'][0]
    assert source['content_redacted'] is True and 'source_ref' not in source
    assert source['content_sha256']==hashlib.sha256(source['content'].encode()).hexdigest()
    assert value['snapshot_sha256']==raw['snapshot_sha256']
    expected=value.pop('display_sha256')
    assert hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()==expected


@pytest.mark.parametrize('changes',[{'choice':'approve'},{'choice':'reject','bot':{'address':'visit_prep','team_revision':1}},
    {'choice':'reject','expected_snapshot_sha256':'a'*64},{'choice':'reject','source_ref':'private'}, {'choice':'reject','expected_version':True}])
def test_decision_has_no_ambiguous_authority_shape(changes):
    value={'expected_version':1,'revision_id':'00000000-0000-4000-8000-000000000001','payload_hash':'a'*64,**changes}
    with pytest.raises(ValidationError): PrepWorkDecision.model_validate(value)

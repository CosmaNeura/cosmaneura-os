"""Pin team-setup request reader: contract header and bounded JSON body."""

import pytest
from pydantic import BaseModel, ConfigDict

from cosmas_os.api.team_setup_schemas import contract_header, read_team_request
from cosmas_os.application.team_setup import MAX_REQUEST_BYTES
from cosmas_os.application.workspace import WorkspaceError


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class Headers:
    def __init__(self, values=None):
        self._values = {
            str(name).lower(): [str(item) for item in items]
            for name, items in (values or {}).items()
        }

    def getlist(self, name):
        return list(self._values.get(str(name).lower(), []))

    def __getitem__(self, name):
        values = self.getlist(name)
        if not values:
            raise KeyError(name)
        return values[0]


class FakeRequest:
    def __init__(self, *, headers=None, query_params=None, chunks=None):
        self.headers = Headers(headers)
        self.query_params = {} if query_params is None else query_params
        self._chunks = [b'{"name":"x"}'] if chunks is None else list(chunks)

    async def stream(self):
        for chunk in self._chunks:
            yield chunk


def baseline(**changes):
    headers = {"content-type": ["application/json"]}
    query_params = {}
    chunks = [b'{"name":"x"}']
    if "headers" in changes:
        headers = changes.pop("headers")
    if "query_params" in changes:
        query_params = changes.pop("query_params")
    if "chunks" in changes:
        chunks = changes.pop("chunks")
    if changes:
        raise TypeError(f"unexpected baseline changes: {sorted(changes)}")
    return FakeRequest(headers=headers, query_params=query_params, chunks=chunks)


def test_contract_header_absent_is_zero():
    assert contract_header(FakeRequest(headers={})) == 0


@pytest.mark.parametrize("value", ["1", "2", "3", "4", "5"])
def test_contract_header_accepts_supported_versions(value):
    assert contract_header(FakeRequest(headers={"x-cosmas-team-contract": [value]})) == int(value)


def test_contract_header_required_without_header():
    with pytest.raises(WorkspaceError) as exc:
        contract_header(FakeRequest(headers={}), required=True)
    assert exc.value.code == "team_contract_required"
    assert exc.value.status == 426


@pytest.mark.parametrize("values", [["6"], ["0"], [""], ["1", "1"]])
def test_contract_header_rejects_unsupported_values(values):
    with pytest.raises(WorkspaceError) as exc:
        contract_header(FakeRequest(headers={"x-cosmas-team-contract": values}))
    assert exc.value.code == "team_contract_unsupported"
    assert exc.value.status == 426


@pytest.mark.asyncio
async def test_read_team_request_baseline_builds_body():
    result = await read_team_request(baseline(), Body)
    assert result.name == "x"


@pytest.mark.asyncio
async def test_read_team_request_accepts_content_type_with_charset():
    request = baseline(headers={"content-type": ["Application/JSON; charset=utf-8"]})
    result = await read_team_request(request, Body)
    assert result.name == "x"


@pytest.mark.asyncio
async def test_read_team_request_accepts_body_split_across_chunks():
    request = baseline(chunks=[b'{"name":', b'"x"}'])
    result = await read_team_request(request, Body)
    assert result.name == "x"


@pytest.mark.asyncio
async def test_read_team_request_accepts_one_authorization_value():
    request = baseline(
        headers={
            "content-type": ["application/json"],
            "authorization": ["Bearer invented-token"],
        }
    )
    result = await read_team_request(request, Body)
    assert result.name == "x"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"query_params": {"x": "1"}},
        {"headers": {"content-type": ["text/plain"]}},
        {"headers": {"content-type": ["application/json", "application/json"]}},
        {
            "headers": {
                "content-type": ["application/json"],
                "authorization": ["a", "b"],
            }
        },
        {
            "headers": {
                "content-type": ["application/json"],
                "content-encoding": ["gzip"],
            }
        },
        {"chunks": [b"{"]},
        {"chunks": [b'{"name":"x","name":"y"}']},
        {"chunks": [b'{"name":"x","other":1}']},
        {"chunks": [b"x" * (MAX_REQUEST_BYTES + 1)]},
    ],
    ids=[
        "nonempty_query",
        "wrong_content_type",
        "duplicate_content_type",
        "duplicate_authorization",
        "content_encoding",
        "invalid_json",
        "duplicate_json_key",
        "extra_field",
        "oversized_body",
    ],
)
async def test_read_team_request_rejects_one_fault(change):
    with pytest.raises(WorkspaceError) as exc:
        await read_team_request(baseline(**change), Body)
    assert exc.value.code == "invalid_team_setup_request"
    assert exc.value.status == 422

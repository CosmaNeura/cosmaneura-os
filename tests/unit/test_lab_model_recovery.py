import httpx
import pytest
from lab.engine import draft_reply
from lab.store import LabError


class Model:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = []

    def reply(self, messages, tools):
        self.calls.append((messages, tools))
        if self.errors:
            raise self.errors.pop(0)
        return {"role": "assistant", "content": "Draft only"}, {"total_tokens": 5}


@pytest.mark.parametrize("error", [httpx.ReadTimeout("private"), httpx.ConnectError("private"), LabError("model_http_503")])
def test_one_retry_keeps_input_and_rechecks_authority(error, monkeypatch):
    monkeypatch.setattr("lab.engine.time.sleep", lambda _: None)
    model, authorities, events = Model([error]), [], []
    result = draft_reply(model, ["same admitted input"], [], lambda: authorities.append(True),
                         lambda kind, **v: events.append((kind, v)))
    assert result[2] == 1 and len(authorities) == 2
    assert model.calls[0] == model.calls[1]
    assert len(events) == 1 and "private" not in str(events)


def test_unknown_second_failure_is_terminal(monkeypatch):
    monkeypatch.setattr("lab.engine.time.sleep", lambda _: None)
    model = Model([httpx.ReadTimeout("private"), httpx.ReadTimeout("private")])
    with pytest.raises(LabError, match="^model_timeout$"):
        draft_reply(model, [], [], lambda: None, lambda *a, **k: None)
    assert len(model.calls) == 2


def test_revocation_before_retry_prevents_second_generation(monkeypatch):
    monkeypatch.setattr("lab.engine.time.sleep", lambda _: None)
    model = Model([httpx.ReadTimeout("private")])
    def authority():
        if model.calls:
            raise LabError("revoked")
    with pytest.raises(LabError, match="revoked"):
        draft_reply(model, [], [], authority, lambda *a, **k: None)
    assert len(model.calls) == 1


@pytest.mark.parametrize("error", ["model_http_401", "model_http_429", "run_budget_exhausted", "invalid_model_usage"])
def test_nontransient_failure_never_retries(error):
    model = Model([LabError(error)])
    with pytest.raises(LabError, match=error):
        draft_reply(model, [], [], lambda: None, lambda *a, **k: None)
    assert len(model.calls) == 1

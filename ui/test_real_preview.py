from ui import adapter, components, real_preview
from ui.api_client import BlueScoreApiClient


def test_api_client_sends_real_list_filters_and_source_type(monkeypatch):
    client = BlueScoreApiClient("http://example.test")
    calls = []

    def fake_request(method, path, *, json=None):
        calls.append((method, path, json))
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    client.list_vessels(
        "real",
        status="partial",
        query="A B",
        limit=25,
        offset=50,
    )
    client.explanation("V1", "real")
    client.ask("V1", "why?", "real")

    assert calls[0] == (
        "GET",
        "/vessels?sourceType=real&limit=25&offset=50&status=partial&query=A+B",
        None,
    )
    assert calls[1] == (
        "GET",
        "/vessels/V1/explanation?sourceType=real",
        None,
    )
    assert calls[2] == (
        "POST",
        "/vessels/V1/questions?sourceType=real",
        {"question": "why?"},
    )


def test_adapter_separates_source_caches_and_real_list_arguments(monkeypatch):
    class FakeApi:
        def __init__(self):
            self.calls = []

        def score(self, vessel_id, source_type="demo"):
            self.calls.append(("score", vessel_id, source_type))
            return {"sourceType": source_type}

        def list_vessels(self, source_type="demo", **kwargs):
            self.calls.append(("list", source_type, kwargs))
            return {"vessels": [], "total": 0, "statusCounts": {}}

    fake = FakeApi()
    monkeypatch.setattr(adapter, "_api", fake)
    adapter.clear_cache()

    assert adapter._score("V1", "demo")["sourceType"] == "demo"
    assert adapter._score("V1", "real")["sourceType"] == "real"
    adapter._score("V1", "real")
    adapter.real_vessel_page(status="partial", query="  abc  ", limit=20, offset=40)

    assert fake.calls.count(("score", "V1", "real")) == 1
    assert ("score", "V1", "demo") in fake.calls
    assert (
        "list",
        "real",
        {"status": "partial", "query": "abc", "limit": 20, "offset": 40},
    ) in fake.calls


def test_real_explanation_is_lazy_and_non_success_never_calls_api(monkeypatch):
    class FakeApi:
        def __init__(self):
            self.explanations = []
            self.questions = []

        def explanation(self, vessel_id, source_type="demo"):
            self.explanations.append((vessel_id, source_type))
            return {"summary": "ok", "sourceType": source_type}

        def ask(self, vessel_id, question, source_type="demo"):
            self.questions.append((vessel_id, question, source_type))
            return {"text": "ok", "sourceType": source_type}

    fake = FakeApi()
    monkeypatch.setattr(adapter, "_api", fake)
    adapter.clear_cache()
    partial = {"status": "partial", "vessel": {"vesselId": "V1"}}
    success = {"status": "success", "vessel": {"vesselId": "V1"}}

    assert adapter.get_real_explanation(partial) is None
    assert adapter.ask_real(partial, "why?") is None
    assert fake.explanations == []
    assert fake.questions == []

    assert adapter.get_real_explanation(success)["sourceType"] == "real"
    assert adapter.ask_real(success, "why?")["sourceType"] == "real"
    assert fake.explanations == [("V1", "real")]
    assert fake.questions == [("V1", "why?", "real")]


def test_real_state_helpers_distinguish_peer_and_event_failures():
    insufficient = {
        "status": "insufficientSample",
        "peerGroup": {"count": 12},
        "axisB": {},
    }
    matching_failed = {
        "status": "matchingFailed",
        "matchingReason": "no valid event",
        "axisB": {},
    }

    assert "12척" in real_preview._status_notice(insufficient)
    assert real_preview._status_notice(matching_failed) == "no valid event"
    assert real_preview._unmatched_reason_text("held_multi").startswith("복수 후보")
    assert real_preview._can_load_explanation({"status": "success"}) is True
    assert real_preview._can_load_explanation(insufficient) is False


def test_real_cards_escape_dynamic_html(monkeypatch):
    rendered = []
    iframe = []
    monkeypatch.setattr(
        components.st,
        "markdown",
        lambda body, **kwargs: rendered.append(body),
    )
    monkeypatch.setattr(
        components,
        "components_html",
        lambda body, **kwargs: iframe.append(body),
    )

    components.real_vessel_meta_card(
        '<img src=x onerror="alert(1)">',
        "<script>alert(2)</script>",
        20,
        3,
        2,
        "<b>snapshot</b>",
    )
    components.real_matching_evidence_card(
        {
            "matchTier": "unmatched",
            "gfwName": "<svg onload=alert(3)>",
            "unmatchedReason": "<raw>",
        },
        "<gear>",
        "<reason>",
    )
    components.real_shap_factor_bars(
        [{"label": "<script>alert(4)</script>", "value": 10, "axis": "a"}]
    )

    html = "".join(rendered + iframe)
    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "<svg onload" not in html
    assert "&lt;script&gt;alert" in html
    assert "&lt;img src=x" in html
    assert "&lt;svg onload" in html


def test_real_preview_has_no_simulation_api_controls():
    names = set(real_preview.render.__code__.co_names)
    assert "simulate" not in names
    assert "simulate_surface" not in names

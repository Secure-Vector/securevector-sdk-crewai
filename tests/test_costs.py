"""Cost tracking (issue #185): usage_metrics extraction, provider/model
normalization, the /api/costs/track POST, and fail-soft behaviour."""

from securevector_sdk_crewai.client import LocalAppClient
from securevector_sdk_crewai.config import Config
from securevector_sdk_crewai.costs import (
    CostTracker,
    crew_model_id,
    infer_provider,
    split_model_id,
    track_crew_usage,
    usage_delta,
    usage_totals,
)


class FakeMetrics:
    def __init__(self, prompt=0, completion=0, cached=0):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.cached_prompt_tokens = cached


class FakeLLM:
    def __init__(self, model):
        self.model = model


class FakeAgent:
    def __init__(self, llm):
        self.llm = llm


class FakeCrew:
    def __init__(self, metrics=None, model="gpt-4o"):
        self.usage_metrics = metrics
        self.agents = [FakeAgent(FakeLLM(model))] if model else []


class CaptureClient:
    def __init__(self):
        self.costs = []

    def record_cost(self, **kwargs):
        self.costs.append(kwargs)
        return True


# --------------------------------------------------------------------- #
# client.record_cost                                                    #
# --------------------------------------------------------------------- #
def test_record_cost_posts_contract_payload():
    c = LocalAppClient(Config())
    seen = {}

    def fake_post(path, body):
        seen["path"], seen["body"] = path, body
        return {"status": "recorded"}

    c._post = fake_post
    c.record_cost(
        agent_id=None, provider="openai", model_id="gpt-4o",
        input_tokens=100, output_tokens=20, input_cached_tokens=5,
    )
    assert seen["path"] == "/api/costs/track"
    assert seen["body"]["agent_id"] == "crewai-agent"
    assert seen["body"]["input_tokens"] == 100


def test_record_cost_fail_soft_when_app_unreachable():
    c = LocalAppClient(Config(base_url="http://127.0.0.1:1"))

    def boom(path, body):
        raise OSError("connection refused")

    c._post = boom
    # Must not raise — cost tracking never breaks the crew.
    c.record_cost(agent_id="a", provider="openai", model_id="gpt-4o",
                  input_tokens=1, output_tokens=1)


# --------------------------------------------------------------------- #
# normalization + usage math                                            #
# --------------------------------------------------------------------- #
def test_split_model_id_handles_litellm_prefixes_and_aliases():
    assert split_model_id("openai/gpt-4o-2024-08-06") == ("openai", "gpt-4o")
    assert split_model_id("anthropic/claude-3-5-sonnet-20241022") == (
        "anthropic", "claude-3-5-sonnet-20241022")
    assert split_model_id("ollama_chat/llama3") == ("ollama", "llama3")
    assert split_model_id("gpt-4o") == (None, "gpt-4o")
    assert split_model_id(None) == (None, "")


def test_infer_provider_heuristics():
    assert infer_provider("gpt-4o") == "openai"
    assert infer_provider("o1-mini") == "openai"
    assert infer_provider("claude-3-5-haiku-20241022") == "anthropic"
    assert infer_provider("gemini-1.5-pro") == "gemini"
    assert infer_provider("command-r") == "cohere"
    assert infer_provider("mystery-model") == ""


def test_usage_totals_reads_metrics_and_defaults():
    assert usage_totals(FakeMetrics(100, 20, 5)) == {
        "prompt": 100, "completion": 20, "cached": 5}
    assert usage_totals(None) == {"prompt": 0, "completion": 0, "cached": 0}
    assert usage_totals({"prompt_tokens": 7, "completion_tokens": 3}) == {
        "prompt": 7, "completion": 3, "cached": 0}


def test_usage_delta_accumulating_and_reset_counters():
    before = {"prompt": 100, "completion": 20, "cached": 0}
    grown = {"prompt": 180, "completion": 50, "cached": 10}
    assert usage_delta(before, grown) == {"prompt": 80, "completion": 30, "cached": 10}
    # counter shrank → metrics were rebuilt for this run → use them as-is
    rebuilt = {"prompt": 60, "completion": 10, "cached": 0}
    assert usage_delta(before, rebuilt) == rebuilt


def test_crew_model_id_reads_first_agent_llm():
    assert crew_model_id(FakeCrew(model="anthropic/claude-3-5-sonnet-20241022")) == \
        "anthropic/claude-3-5-sonnet-20241022"
    # string llm (older crewai)
    crew = FakeCrew(model=None)
    crew.agents = [FakeAgent("gpt-4o-mini")]
    assert crew_model_id(crew) == "gpt-4o-mini"
    assert crew_model_id(FakeCrew(model=None)) == ""


# --------------------------------------------------------------------- #
# CostTracker + track_crew_usage                                        #
# --------------------------------------------------------------------- #
def test_tracker_records_crew_usage():
    client = CaptureClient()
    tracker = CostTracker(Config(), client=client)
    crew = FakeCrew(FakeMetrics(5300, 870, 4000), model="openai/gpt-4o-2024-11-20")
    assert tracker.record_crew(crew) is True
    assert client.costs == [{
        "agent_id": "crewai-agent",
        "provider": "openai",
        "model_id": "gpt-4o",
        "input_tokens": 5300,
        "output_tokens": 870,
        "input_cached_tokens": 4000,
    }]


def test_tracker_records_delta_since_before_snapshot():
    client = CaptureClient()
    tracker = CostTracker(Config(), client=client)
    crew = FakeCrew(FakeMetrics(180, 50, 10))
    before = {"prompt": 100, "completion": 20, "cached": 0}
    assert tracker.record_crew(crew, before=before) is True
    assert client.costs[0]["input_tokens"] == 80
    assert client.costs[0]["output_tokens"] == 30


def test_tracker_skips_empty_usage_or_unknown_model():
    client = CaptureClient()
    tracker = CostTracker(Config(), client=client)
    assert tracker.record_crew(FakeCrew(None)) is False
    assert tracker.record_crew(FakeCrew(FakeMetrics(0, 0))) is False
    assert tracker.record_crew(FakeCrew(FakeMetrics(10, 5), model=None)) is False
    assert client.costs == []


def test_tracker_disabled_config_posts_nothing():
    client = CaptureClient()
    tracker = CostTracker(Config(enabled=False), client=client)
    assert tracker.record_crew(FakeCrew(FakeMetrics(10, 5))) is False
    assert client.costs == []


def test_tracker_never_raises_on_client_failure():
    class BoomClient:
        def record_cost(self, **kwargs):
            raise RuntimeError("boom")

    tracker = CostTracker(Config(), client=BoomClient())
    assert tracker.record_crew(FakeCrew(FakeMetrics(10, 5))) is False


def test_track_crew_usage_explicit_entry_point():
    client = CaptureClient()
    crew = FakeCrew(FakeMetrics(100, 25), model="claude-3-5-haiku-20241022")
    assert track_crew_usage(crew, agent_id="research-crew", client=client) is True
    assert client.costs[0]["agent_id"] == "research-crew"
    assert client.costs[0]["provider"] == "anthropic"


def test_agent_id_from_config_and_env(monkeypatch):
    client = CaptureClient()
    crew = FakeCrew(FakeMetrics(10, 5))
    CostTracker(Config(agent_id="from-config"), client=client).record_crew(crew)
    monkeypatch.setenv("SECUREVECTOR_SDK_AGENT_ID", "env-agent")
    CostTracker(Config.from_env(), client=client).record_crew(crew)
    assert [c["agent_id"] for c in client.costs] == ["from-config", "env-agent"]

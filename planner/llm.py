import json
import os
import threading

from openai import OpenAI

from .types import ChatResult, UsageInfo

_client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL"),
    api_key=os.getenv("LLM_API_KEY"),
    timeout=float(os.getenv("LLM_TIMEOUT", "60")),
)
_model = os.getenv("LLM_MODEL_ID", "deepseek-chat")

# 价格（USD per 1M tokens），可通过环境变量覆盖。
# 默认值参考 DeepSeek-chat 标准价；如服务商调价或换模型请用 env 覆盖。
_INPUT_PRICE = float(os.getenv("LLM_INPUT_USD_PER_M", "0.27"))
_CACHED_INPUT_PRICE = float(os.getenv("LLM_CACHED_INPUT_USD_PER_M", "0.07"))
_OUTPUT_PRICE = float(os.getenv("LLM_OUTPUT_USD_PER_M", "1.10"))


def _calc_cost(prompt_tokens: int, completion_tokens: int, cached_tokens: int) -> float:
    fresh = max(0, prompt_tokens - cached_tokens)
    return (
        fresh * _INPUT_PRICE / 1_000_000
        + cached_tokens * _CACHED_INPUT_PRICE / 1_000_000
        + completion_tokens * _OUTPUT_PRICE / 1_000_000
    )


class UsageTracker:
    """线程安全的 token / cost 累加器，分总账和 stage 子账。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._totals: UsageInfo = UsageInfo()
        self._by_stage: dict[str, UsageInfo] = {}

    def record(self, usage: UsageInfo, stage: str) -> None:
        with self._lock:
            self._totals = self._totals + usage
            prev = self._by_stage.get(stage, UsageInfo())
            self._by_stage[stage] = prev + usage

    def snapshot(self) -> tuple[UsageInfo, dict[str, UsageInfo]]:
        with self._lock:
            return self._totals, dict(self._by_stage)

    def reset(self) -> None:
        with self._lock:
            self._totals = UsageInfo()
            self._by_stage = {}


_tracker = UsageTracker()


def get_tracker() -> UsageTracker:
    return _tracker


def _extract_usage(resp_usage) -> tuple[int, int, int]:
    if resp_usage is None:
        return 0, 0, 0
    prompt_tokens = getattr(resp_usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(resp_usage, "completion_tokens", 0) or 0
    cached_tokens = 0
    details = getattr(resp_usage, "prompt_tokens_details", None)
    if details is not None:
        cached_tokens = getattr(details, "cached_tokens", 0) or 0
    # DeepSeek 兼容字段
    hit = getattr(resp_usage, "prompt_cache_hit_tokens", 0) or 0
    if hit:
        cached_tokens = max(cached_tokens, hit)
    return prompt_tokens, completion_tokens, cached_tokens


def chat(
    messages: list[dict],
    temperature: float = 0.3,
    json_mode: bool = False,
    stage: str = "other",
) -> ChatResult:
    kwargs: dict = {
        "model": _model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _client.chat.completions.create(**kwargs)

    content = resp.choices[0].message.content or ""
    prompt_tokens, completion_tokens, cached_tokens = _extract_usage(resp.usage)
    cost = _calc_cost(prompt_tokens, completion_tokens, cached_tokens)
    usage = UsageInfo(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        cost_usd=cost,
        calls=1,
    )
    _tracker.record(usage, stage)
    return ChatResult(content=content, usage=usage, stage=stage)


def chat_json(
    messages: list[dict],
    temperature: float = 0.2,
    stage: str = "other",
) -> tuple[dict, UsageInfo]:
    result = chat(messages, temperature=temperature, json_mode=True, stage=stage)
    try:
        return json.loads(result.content), result.usage
    except json.JSONDecodeError as e:
        raise ValueError(
            f"LLM returned invalid JSON: {e}\n---raw---\n{result.content}"
        ) from e

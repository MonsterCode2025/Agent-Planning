import json
import os

from openai import OpenAI

_client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL"),
    api_key=os.getenv("LLM_API_KEY"),
    timeout=float(os.getenv("LLM_TIMEOUT", "60")),
)
_model = os.getenv("LLM_MODEL_ID", "deepseek-chat")


def chat(messages: list[dict], temperature: float = 0.3, json_mode: bool = False) -> str:
    kwargs: dict = {
        "model": _model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def chat_json(messages: list[dict], temperature: float = 0.2) -> dict:
    text = chat(messages, temperature=temperature, json_mode=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\n---raw---\n{text}") from e

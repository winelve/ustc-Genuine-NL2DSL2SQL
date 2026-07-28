"""ChatEndpoint：OpenAI 兼容 /chat/completions 的最小封装。

客户端初始化、密钥检查、参数拼装只在这里写一份，APIModel（CT-3 直出）和
model/pipeline（多阶段生成）共用。密钥只走环境变量（铁律 #2）。
"""

from __future__ import annotations

import os
from time import perf_counter

from model.metrics import record_api_call


def _response_usage(response) -> dict[str, int | None] | None:
    """Flatten an OpenAI-compatible usage object without depending on its type."""

    def value(obj, name: str):
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    usage = value(response, "usage")
    if usage is None:
        return None
    details = value(usage, "completion_tokens_details")
    return {
        "prompt_tokens": value(usage, "prompt_tokens"),
        "completion_tokens": value(usage, "completion_tokens"),
        "total_tokens": value(usage, "total_tokens"),
        "prompt_cache_hit_tokens": value(usage, "prompt_cache_hit_tokens"),
        "prompt_cache_miss_tokens": value(usage, "prompt_cache_miss_tokens"),
        "reasoning_tokens": value(details, "reasoning_tokens"),
    }


class ChatEndpoint:
    def __init__(
        self,
        base_url: str,
        model: str,
        key_env: str,
        request_params: dict | None = None,
    ) -> None:
        from openai import OpenAI  # 懒导入：没装 openai 不影响其他模型

        key = os.environ.get(key_env)
        if not key:
            raise RuntimeError(f"缺少环境变量 {key_env}（base_url={base_url}）")
        # SDK 自带限流/超时重试（默认 2 次），不另写重试逻辑
        self._client = OpenAI(api_key=key, base_url=base_url)
        self.model = model
        self.request_params = dict(request_params or {})

    def chat_messages(self, messages: list[dict], **overrides) -> str:
        """发一段完整对话（修复循环需要带历史），返回回复正文。"""
        params = {**self.request_params, **overrides}
        started_at = perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self.model, messages=messages, **params,
            )
        except Exception as exc:
            record_api_call(
                perf_counter() - started_at,
                error=type(exc).__name__,
            )
            raise
        record_api_call(
            perf_counter() - started_at,
            usage=_response_usage(response),
        )
        # 思维链在 message.reasoning_content，与 content 同级；这里只要最终答案
        return response.choices[0].message.content or ""

    def chat(self, system: str, user: str, **overrides) -> str:
        """发一轮 system+user 对话；overrides 覆盖 request_params。"""
        return self.chat_messages(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            **overrides,
        )

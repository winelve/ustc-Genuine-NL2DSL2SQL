"""API 模型：通过 OpenAI 兼容的 /chat/completions 生成 SQL。

每个具体模型是 APIModel 的一个子类，填 base_url / model / key_env 三个类属性，
在 model/__init__.py 的 MODELS 注册（铁律 #2：模型专属参数随模型走，
不进全局 config；密钥只走环境变量）：

    $env:DEEPSEEK_API_KEY = "sk-..."
    python -m model --model deepseek-v4-flash --data en_dev --limit 5 --eval

本地部署（vLLM / Ollama）只要暴露 OpenAI 兼容接口，base_url 指向本机即可。
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from archer_eval.data import Sample
from archer_eval.progress import Progress
from model.base import SQLGenerator
from model.prompts import build_ct3_prompt
from config import API_CONCURRENCY

# CT-3 prompt 是论文的 completion 式（以 "SELECT" 结尾）。发给 chat 接口时
# 用这句要求模型输出完整语句，而不是回一段解释或只续写后半句。
SYSTEM_PROMPT = "Answer with one complete SQLite statement. No explanation."

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(reply: str) -> str:
    """取出回复里的 SQL —— 模型常无视指令把语句包在 markdown 代码块里。"""
    fenced = _FENCE.search(reply)
    return (fenced.group(1) if fenced else reply).strip()


class APIModel(SQLGenerator):
    base_url: str      # OpenAI 兼容接口地址
    model: str         # 请求体里的模型名（name 是注册名，两者可不同）
    key_env: str       # 密钥所在环境变量的名字

    temperature = 0.0
    concurrency = API_CONCURRENCY    # 同时在飞的请求数，触发限流就在子类调小

    def __init__(self) -> None:
        from openai import OpenAI  # 懒导入：没装 openai 也不影响其他模型

        key = os.environ.get(self.key_env)
        if not key:
            raise RuntimeError(f"模型 {self.name} 缺少环境变量 {self.key_env}")
        # SDK 自带限流/超时重试（默认 2 次），不另写重试逻辑
        self._client = OpenAI(api_key=key, base_url=self.base_url)

    def predict(self, sample: Sample, db_path: Path) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_ct3_prompt(sample, db_path)},
            ],
        )
        return extract_sql(response.choices[0].message.content or "")

    def predict_all(
        self, samples: list[Sample], db_paths: list[Path], progress: bool = True
    ) -> list[str]:
        """并发发请求；结果保持输入顺序，单条失败记空串（同基类约定）。"""

        def one(indexed: tuple[int, tuple[Sample, Path]]) -> tuple[str, str | None]:
            i, (sample, db_path) = indexed
            try:
                return self.predict(sample, db_path), None
            except Exception as e:
                # 失败消息带回主线程统一打印，工作线程不碰终端
                return "", f"  sample {i} failed: {type(e).__name__}: {e}"

        bar = Progress(len(samples), "generate", enabled=progress)
        preds = []
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            for sql, error in pool.map(one, enumerate(zip(samples, db_paths))):
                if error:
                    bar.write(error)
                preds.append(sql)
                bar.step()
        return preds


class GPT4oMini(APIModel):
    name = "gpt-4o-mini"
    base_url = "https://api.openai.com/v1"
    model = "gpt-4o-mini"
    key_env = "OPENAI_API_KEY"


class DeepSeekChat(APIModel):
    name = "deepseek-v4-flash"
    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-v4-flash"
    key_env = "DEEPSEEK_API_KEY"

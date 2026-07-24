"""API 模型：通过 OpenAI 兼容的 /chat/completions 生成 SQL。

每个具体模型是 APIModel 的一个子类，填 base_url / model / key_env 三个类属性，
在 model/__init__.py 的 MODELS 注册（铁律 #2：模型专属参数随模型走，
不进全局 config；密钥只走环境变量）：

    $env:DEEPSEEK_API_KEY = "sk-..."
    python -m model --model deepseek-v4-flash --data en_dev --limit 5 --eval

本地部署（vLLM / Ollama）只要暴露 OpenAI 兼容接口，base_url 指向本机即可。

temperature、思考开关等请求参数放在类属性 request_params 里，随请求原样发出，
同样随模型走；DeepSeek 思考模式的取舍见 DeepSeekFlash / DeepSeekFlashThinking。
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from archer_eval.data import Sample
from archer_eval.progress import Progress
from model.base import SQLGenerator
from model.llm import ChatEndpoint
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

    concurrency = API_CONCURRENCY    # 同时在飞的请求数，触发限流就在子类调小

    # 除 model / messages 外要发的全部请求参数，所见即所发，子类整体覆盖（不合并）；
    # 厂商扩展字段（如 DeepSeek 的 thinking）包在 "extra_body" 里。默认贪心解码。
    request_params: dict = {"temperature": 0.0}

    # 约定附录开关（K1–K11，追加式注入同 dslgen 那边的做法）：
    # 关闭时 system 消息与基线逐字节相同，有测试锁死
    conventions = False

    def __init__(self) -> None:
        # 客户端封装统一在 model/llm.py 的 ChatEndpoint，pipeline 与此共用
        self._endpoint = ChatEndpoint(
            base_url=self.base_url,
            model=self.model,
            key_env=self.key_env,
            request_params=self.request_params,
        )

    def _system(self) -> str:
        """基线 system + 可选约定附录。附录是追加式的——基线消息逐字节不变。"""
        if not self.conventions:
            return SYSTEM_PROMPT
        from model.pipeline.conventions import conventions_block
        from model.pipeline.templates import render
        return SYSTEM_PROMPT + "\n" + render("direct.conventions",
                                             conventions=conventions_block())

    def predict(self, sample: Sample, db_path: Path) -> str:
        reply = self._endpoint.chat(self._system(), build_ct3_prompt(sample, db_path))
        return extract_sql(reply)

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


class DeepSeekFlash(APIModel):
    name = "flash-direct"
    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-v4-flash"
    key_env = "DEEPSEEK_API_KEY"

    # DeepSeek 服务端默认开思考，而思考模式会静默忽略 temperature 等采样参数
    # （文档《思考模式》）。主线要可复现的贪心解码，所以必须显式关掉思考。
    request_params = {
        "temperature": 0.0,
        "extra_body": {"thinking": {"type": "disabled"}},
    }


class DeepSeekFlashThinking(DeepSeekFlash):
    """开思考的对照组。单独注册名 = 单独的预测/结果文件，和主线互不覆盖。"""

    name = "flash-t-direct"

    # 开思考后采样参数一律失效，结果不可复现，且更慢更贵。不发 temperature，
    # 免得看起来像在生效。思考强度服务端默认 high，要更强加顶层参数
    # reasoning_effort="max"（low/medium 会被映射回 high，没有真正的低档）。
    request_params = {"extra_body": {"thinking": {"type": "enabled"}}}


class DeepSeekPro(APIModel):
    name = "pro-direct"
    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-v4-pro"
    key_env = "DEEPSEEK_API_KEY"
    request_params = {
        "temperature": 0.0,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    
    
class DeepSeekProThinking(DeepSeekPro):
    name = "pro-t-direct"
    request_params = {"extra_body": {"thinking": {"type": "enabled"}}}


class DeepSeekProThinkingConv(DeepSeekProThinking):
    """直出 + 约定文本（K1–K11）：满配 leave-one-out 的"− DSL 声明层"臂。

    声明层拿掉后校验/修复随之消失，剩下的就是裸直出 + 同一份约定 prose。
    与 pro-t-direct 的唯一差异 = conventions；与 dsl-conv 对比读出
    "约定的收益是否依赖声明层"（方案见 docs/ABLATION.md）。
    """

    name = "pro-t-direct-conv"
    conventions = True

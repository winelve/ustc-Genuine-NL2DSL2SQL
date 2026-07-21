"""单行文本进度条：生成侧和评测侧共用（model 可 import archer_eval，铁律 #1）。

用法：
    bar = Progress(len(items), "generate", enabled=progress)
    for item in items:
        ...                      # 处理一条
        bar.write("出错了")       # 可选：打印消息而不冲花进度条
        bar.step()               # 前进一格，走到 total 时自动换行
"""

from __future__ import annotations

import sys


class Progress:
    WIDTH = 24     # bar 的字符宽度
    EVERY = 20     # 非终端（重定向/管道）时退化为每 N 条打一行

    def __init__(self, total: int, label: str = "", enabled: bool = True) -> None:
        self.total = total
        self.label = label
        self.enabled = enabled and total > 0
        self.done = 0
        self._tty = sys.stdout.isatty()
        self._last_len = 0

    def step(self) -> None:
        if not self.enabled:
            return
        self.done += 1
        filled = round(self.WIDTH * self.done / self.total)
        line = f"{self.label} [{'#' * filled}{'-' * (self.WIDTH - filled)}] {self.done}/{self.total}"
        if self._tty:
            self._last_len = len(line)
            print("\r" + line, end="\n" if self.done == self.total else "", flush=True)
        elif self.done % self.EVERY == 0 or self.done == self.total:
            print(line, flush=True)

    def write(self, message: str) -> None:
        """打印一行消息：先用空格盖掉当前的 bar 行，bar 在下一次 step() 时重绘。"""
        if self.enabled and self._tty:
            print("\r" + message.ljust(self._last_len), flush=True)
        else:
            print(message)

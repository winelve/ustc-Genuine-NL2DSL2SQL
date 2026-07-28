"""预览指定 pipeline 模型实际发送的首轮消息（不初始化、不调用 API）。

    python -m model.pipeline --model pro-t-dsl-fs --data en_dev --preview 0
"""

from __future__ import annotations

import argparse

import config
from archer_eval.data import load_dataset, resolve_dataset
from archer_eval.evaluate import find_db_file
from model import MODELS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="model.pipeline",
        description="Preview the selected pipeline model's exact initial messages",
    )
    parser.add_argument("--model", required=True, choices=sorted(MODELS),
                        help="registered model name")
    parser.add_argument("--data", required=True,
                        help=f"one of {', '.join(config.DATASETS)} or a JSON file path")
    parser.add_argument("--preview", type=int, required=True, metavar="N",
                        help="dataset index of the sample to preview")
    args = parser.parse_args(argv)

    sample = load_dataset(resolve_dataset(args.data))[args.preview]
    db_path = find_db_file(config.db_dir_for(args.data), sample.db_id)
    model_class = MODELS[args.model]
    factory = getattr(model_class, "for_preview", None)
    if not callable(factory):
        raise ValueError(
            f"model {args.model!r} does not support exact pipeline preview"
        )
    generator = factory()
    messages = generator.preview_messages(sample, db_path)

    print(
        f"model={args.model}  data={args.data}  index={args.preview}  "
        f"db_id={sample.db_id}"
    )
    for message in messages:
        role = message["role"]
        print(f"{'=' * 28} {role} {'=' * 28}")
        print(message["content"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

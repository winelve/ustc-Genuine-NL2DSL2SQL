# 允许不执行 pip install -e . 也能直接跑 pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

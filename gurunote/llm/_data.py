"""패키지 안 데이터 파일의 위치.

`gurunote/llm/` 하위 모듈에서 `Path(__file__).parent` 를 쓰면 `gurunote/llm/` 을
가리켜 `gurunote/data/` 를 놓친다. 해석을 여기 한 곳으로 모은다.
"""
from __future__ import annotations

from pathlib import Path

# gurunote/llm/_data.py → parents[1] 이 gurunote/
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

__all__ = ["DATA_DIR"]

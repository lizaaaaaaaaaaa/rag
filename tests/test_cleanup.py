# tests/test_cleanup.py
import re
from utils.cleanup import cleanup_answer

def test_cleanup_basic():
    src = "- Foo\n- Foo\n\n• Bar"
    assert cleanup_answer(src) == "- Foo\n- Bar"

def test_cleanup_max_lines():
    # 30 行 → 20 行に切り詰められるか
    text = "\n".join(f"- Line {i}" for i in range(30))
    cleaned = cleanup_answer(text, max_lines=20)
    assert len(cleaned.splitlines()) == 20
    # 1行目・20行目の内容をざっくりチェック
    assert cleaned.splitlines()[0] == "- Line 0"
    assert cleaned.splitlines()[-1] == "- Line 19"

def test_cleanup_duplicate_bullets():
    src = "• Apple\n・Apple\n- Banana"
    cleaned = cleanup_answer(src)
    assert "- Apple" in cleaned
    assert cleaned.count("Apple") == 1
    assert "- Banana" in cleaned

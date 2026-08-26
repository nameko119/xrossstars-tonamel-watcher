"""JS版の検索がPython版と同じ結果になるかを確かめる。

  python -m tests.test_parity

Python側で答えを出し、同じ問いをNode.jsに解かせて突き合わせる。
Webページとbotはどちらもbot/search.js（JS版）を使うので、
ここがズレると「Webでは出るのにbotでは出ない」といった事故になる。

Node.js が入っていない環境ではスキップする（Python側のテストは別途通る）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import Competition          # noqa: E402
from src.normalize import normalize_all     # noqa: E402
from src.search import (                    # noqa: E402
    PERIOD_CHOICES, Query, count, period_range, search,
)

HERE = Path(__file__).resolve().parent
TODAY = date(2026, 8, 26)


def main() -> int:
    print("JS版とPython版の検索結果を突き合わせます")

    if not shutil.which("node"):
        print("  ⚠️  Node.js が見つからないためスキップしました")
        print("     （Webページとbotの動作確認には Node.js が必要です）")
        return 0

    raw = json.loads((HERE / "sample_data.json").read_text(encoding="utf-8"))
    comps = [Competition.from_dict(d) for d in raw["competitions"].values()]
    normalize_all(comps)

    cases = json.loads((HERE / "parity_queries.json").read_text(encoding="utf-8"))

    results, counts = {}, {}
    for case in cases:
        q = Query(**case["query"])
        results[case["name"]] = [c.id for c in search(comps, q, today=TODAY)]
        counts[case["name"]] = count(comps, q, today=TODAY)

    periods = {name: list(period_range(name, TODAY)) for name in PERIOD_CHOICES}

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        data_path = tmp / "data.json"
        expected_path = tmp / "expected.json"
        # JS側はPythonが書き出したJSONを読む。正規化フィールドが
        # ちゃんと保存されているかの確認も兼ねている。
        data_path.write_text(
            json.dumps([c.to_dict() for c in comps], ensure_ascii=False),
            encoding="utf-8")
        expected_path.write_text(json.dumps({
            "today": TODAY.isoformat(),
            "results": results,
            "counts": counts,
            "periods": periods,
        }, ensure_ascii=False), encoding="utf-8")

        proc = subprocess.run(
            ["node", str(HERE / "test_parity.js"),
             str(data_path), str(HERE / "parity_queries.json"), str(expected_path)],
            capture_output=True, text=True,
        )
    print(proc.stdout, end="")
    if proc.stderr.strip():
        print(proc.stderr, file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())

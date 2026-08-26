"""Discord bot（Cloudflare Worker）の動作確認を走らせる。

  python -m tests.test_bot

Cloudflareにデプロイする前に、手元で「本当に動くか」を確かめるためのもの。
本物のEd25519鍵で署名したリクエストを作ってWorkerに投げるので、
署名検証が壊れていればここで落ちる。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.build_bot import build as build_bundle   # noqa: E402
from src.models import Competition                # noqa: E402
from src.normalize import normalize_all           # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> int:
    if not shutil.which("node"):
        print("⚠️  Node.js が見つからないためスキップしました")
        return 0

    raw = json.loads((HERE / "sample_data.json").read_text(encoding="utf-8"))
    comps = [Competition.from_dict(d) for d in raw["competitions"].values()]
    normalize_all(comps)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Workerは ES Module なので、Nodeに読ませるため拡張子を .mjs にして置く
        bundle = tmp / "worker.bundle.mjs"
        bundle.write_text(build_bundle(), encoding="utf-8")
        data = tmp / "data.json"
        data.write_text(json.dumps([c.to_dict() for c in comps], ensure_ascii=False),
                        encoding="utf-8")

        proc = subprocess.run(
            ["node", str(HERE / "test_bot.mjs"), str(bundle), str(data)],
            capture_output=True, text=True,
        )
    print(proc.stdout, end="")
    if proc.stderr.strip():
        print(proc.stderr, file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())

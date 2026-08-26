"""Cloudflareに貼り付ける1ファイル版（bot/worker.bundle.js）を作る。

  python -m src.build_bot

bot/search.js と bot/worker.js を連結するだけ。
importを使わない構成にしてあるので、Cloudflareの画面にそのまま貼れる。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEARCH_JS = ROOT / "bot" / "search.js"
WORKER_JS = ROOT / "bot" / "worker.js"
BUNDLE = ROOT / "bot" / "worker.bundle.js"

HEADER = """/* ==========================================================================
 * このファイルは自動生成です。直接編集しないでください。
 *   もと: bot/search.js + bot/worker.js
 *   作り直す: python -m src.build_bot
 *
 * Cloudflare Workers の編集画面に、このファイルの中身をすべて貼り付けます。
 * ========================================================================== */
"""


def build() -> str:
    search = SEARCH_JS.read_text(encoding="utf-8")
    # Node用の1行はWorkerに要らない
    search = search.replace(
        'if (typeof module !== "undefined" && module.exports) module.exports = XSSearch;', "")
    worker = WORKER_JS.read_text(encoding="utf-8")
    return f"{HEADER}\n{search.strip()}\n\n{worker.strip()}\n"


def write(path: Path | None = None) -> Path:
    path = path or BUNDLE
    path.write_text(build(), encoding="utf-8")
    return path


if __name__ == "__main__":
    p = write()
    print(f"{p} を作成しました（{p.stat().st_size:,} バイト）")

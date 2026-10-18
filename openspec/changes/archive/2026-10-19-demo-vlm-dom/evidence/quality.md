# 自動試験と品質確認

- 実施日: 2026-10-18
- 環境: macOS (Darwin)、Python 3.13.15、pytest 9.1.1、Ollama 0.40.4
- 対象: `demo-vlm-dom` の実装と OpenSpec change

| コマンド | 結果 |
| --- | --- |
| `uv run --locked pytest` | 89 件成功 (`npm run check` 内で実行) |
| `uv run --locked ruff check .` | 成功 |
| `uv run --locked ruff format --check .` | 成功 |
| `uv run --locked pyright` | 0 errors |
| `uv run --locked pre-commit run --all-files` | 全フック成功 |
| `npm run check` | OpenSpec 厳格検証、format、lint、型検査、89 件の試験、リポジトリ検査、トレーサビリティ検査が成功 |
| `uv run --locked python scripts/check_openspec_traceability.py --change demo-vlm-dom --phase implementation` | 参照テストの収集を含め成功 |

試験の Ollama 応答には模擬 HTTP を使用した。
別途、Ollama 0.40.4 の実モデルで VLM 空要求、画像解析、DOM 固定質問、車両判定と CLI からの PNG 保存を合成画像で確認した。
VLM は車両を 1 件返し、DOM は `high` を返した。CLI は成功 1 件 / 失敗 0 件で、1280×720 px の PNG を出力した。
実走行画像による受け入れ結果は、この記録に含まない。

## 2026-10-19 の追加確認

- macOS、Python 3.13.15 で `npm run check` を実行し、pytest 94 件、Ruff、Pyright、リポジトリ検査、OpenSpec 厳格検証、実装段階のトレーサビリティ検査が成功した。
- `uv run --locked pre-commit run --all-files` の全フック、`npx --no-install openspec validate demo-vlm-dom --strict`、`uv run --locked python scripts/check_openspec_traceability.py --change demo-vlm-dom --phase implementation` が成功した。
- 遠方車両を DOM の前に低へ分類する境界と車線不明の扱いを `TC-021` で確認した。DOM に自車線、位置関係、見かけの近さを渡す契約を `TC-020` で確認した。
- 実モデル5枚の最終実行は `evidence/acceptance.md` に記録した。自動試験は遠方小車両の検出精度を保証しない。

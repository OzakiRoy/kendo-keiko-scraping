# 次の作業

このZIPは、既存のスクレイパーを壊さずにサービス用JSON出力へ進めるための初期ファイルです。

## 追加ファイル

- `data/organizations.json`: 団体マスタ
- `export_events.py`: スクレイピング結果を `data/events.json` に保存する変換レイヤー
- `docs/data-model.md`: データ設計メモ
- `docs/architecture.md`: AWS構成メモ

## 実行例

```bash
python export_events.py
```

剣睦会だけ確認:

```bash
python export_events.py --group kenbokukai --format text --debug
```

標準出力を抑えてJSONだけ保存:

```bash
python export_events.py --no-stdout
```

出力先:

```text
data/events.json
```

## コミット例

```bash
git add data/organizations.json export_events.py docs/data-model.md docs/architecture.md README-next.md
git commit -m "Add service event export JSON"
```

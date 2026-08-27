# 今週末の稽古会 Story画像生成

## 目的

本番公開済みの `https://kendo-keiko.com/events.json` から、指定した土曜日と翌日曜日の稽古会を抽出し、Instagram Story向けのPNGを生成する。

このCLIは画像生成までを担当する。Instagram投稿、AWS定期実行、S3アップロード、Publisherへの組み込みは行わない。

## セットアップ

Story生成専用の依存を、通常のLambda依存と分けてインストールする。

```bash
python -m venv .venv-story
.venv-story/bin/python -m pip install -r requirements-story.txt
```

## 実行

`--date` には対象週末の土曜日を必ず指定する。日曜日や平日は自動補正せずエラーにする。

```bash
.venv-story/bin/python scripts/generate_weekend_story.py \
  --date 2026-08-29 \
  --output output/weekend-story.png
```

テスト用fixtureを使い、ネットワークへ接続しない場合:

```bash
.venv-story/bin/python scripts/generate_weekend_story.py \
  --date 2026-08-29 \
  --events-file tests/fixtures/weekend_story_events.json \
  --output output/weekend-story.png
```

1ページの場合は指定した名前をそのまま使う。複数ページの場合は決定的な連番を付ける。

```text
output/weekend-story-01.png
output/weekend-story-02.png
```

対象イベントが0件の場合は画像を作らず、標準エラーへ `[NO_EVENTS]` を出して終了コード `3` を返す。これはCLIの故障とは区別できるが、将来の自動実行で投稿をスキップし、運用者へ通知できる非ゼロ終了とする。

## 入力と文字列

- 通常入力は本番 `https://kendo-keiko.com/events.json`
- 対応schemaは実物で確認した `public-events-0.3`
- `timezone` は `Asia/Tokyo` を必須とする
- `organization_name`、`title`、`venue`、`area`、`fee`、`access` はUnicode正規化、表記変換、言い換えを行わない
- feeが `null` の場合は参加費行を表示しない
- accessは初期テンプレートの表示対象ではないが、表示モデルに元の値を保持する
- 参加条件はサイトと同じ `kendo_keiko.static_site.PARTICIPATION_LABELS` を使用する

カードは最大5件を目安とし、実際の改行後の高さでページを分割する。1イベントが1ページへ収まらない場合、文字を削除・省略せずevent IDを表示して停止する。

## フォント

`assets/fonts/NotoSansJP[wght].ttf` を明示的に読み込む。OSのフォント探索や暗黙のフォールバックは行わない。

フォントはGoogle Fonts公式リポジトリのNoto Sans JPを無改変で同梱する。

- 配布元: `https://github.com/google/fonts/tree/295d98a7a0c17c68f1341eaeea354e7960ea70d3/ofl/notosansjp`
- ライセンス: SIL Open Font License 1.1
- ライセンス本文: `assets/fonts/OFL.txt`
- Copyright: 2014-2021 Adobe, Reserved Font Name `Source`
- font SHA-256: `c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f`

OFL 1.1は、フォント単体で販売しないこと、著作権表示とライセンスを同梱すること等を条件に、無改変フォントをソフトウェアへ同梱・再配布することを許可している。生成されたPNG自体へOFLを適用する必要はない。

テストでは「劔」「剱」が欠落文字の表示と異なるグリフとして描画できることを確認する。

## テスト

```bash
.venv-story/bin/python -m unittest -v tests.test_weekend_story
.venv-story/bin/python -m unittest discover -s tests -v
```

自動テストはfixtureを使用し、本番events.jsonや外部ネットワークへ接続しない。

## AWS自動化の残課題

- Pillowとフォントを含む専用Lambda ZIP、Layer、またはコンテナの比較
- EventBridge SchedulerのJST設定
- Publisher完了後に鮮度を検証して生成する順序制御
- 出力S3キー、保持期間、再実行時の上書き規則
- 0件、取得失敗、レイアウト失敗の通知
- 複数ページ成果物の冪等性と監視

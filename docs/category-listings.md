# 種別フィルターとカテゴリ一覧

## 掲載ルール

| URL | 対象 | 種別フィルター |
| --- | --- | --- |
| `/` | 公開済みイベントすべて | すべて（初期値）／稽古会／錬成会・練習試合 |
| `/keiko/` | `open_keiko`, `federation_keiko` | ページの対象を固定 |
| `/renseikai/` | `adult_renseikai` | ページの対象を固定 |

未知・欠損・nullのevent_typeは「種別未分類」。総合一覧の「すべて」に残し、カテゴリ一覧および総合の種別指定時には含めない。タイトル・団体名・参加条件から種別を推測しない。既存の合同稽古会はopen_keikoを維持する。adult_renseikaiの登録時は、大人が外部参加できることを公式情報で確認する。旋風等の登録は別Issue／PRで扱う。

公開判定は従来の `merge_public_events` が担当する。過去・中止・アーカイブ除外、手動優先の重複統合を変更しない。種別の追加による既存データ書き換えは行わない。

`kendo_keiko/listing.py` が分類・ラベル・ページ定義の正。Python生成時に定義をHTMLの `listing-config` JSONへ埋め込み、JavaScriptもそれを読む。`public/index.html` は1つの共通テンプレートで、カテゴリHTMLはGitへ複製して管理しない。定義変更後はテンプレートの生成領域も同期する（下記）。

各ページの静的カード・件数・選択肢とJSの初期表示は同じ対象で開催日・開始時刻・団体ID・event ID順。団体・地域・参加条件の選択肢はページ全体の対象から作る。総合で種別を切り替えてもほかの条件を保持しANDで絞り込むため、0件になる組み合わせも選択可能。条件解除はページの対象内へ戻す。JSON取得失敗・JS無効時は静的カード・0件表示と通常リンクを維持する。

## ローカル開発と検証

このcheckoutの `.venv` を使う。新規環境でのみ、開発依存とブラウザを次のように準備する。導入済みならインストール・再ダウンロードは不要。

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/browsers" python -m playwright install chromium
```

`requirements-dev.txt` はStoryテスト用Pillowも含む。Playwright 1.63.0、Chromium revision 1243を使用。ブラウザ・開発依存はLambda ZIPには含めない。実ブラウザ検証は必須で、依存不足をskipしない。

### WSL2 / Ubuntu 24.04 amd64での共有ライブラリ準備

今回不足していたのはlibnspr4・libnss3・libasound2t64。次の方法はOSへインストールせず、配布パッケージをプロジェクト内に展開する。導入済みなら再実行しない。別OS・アーキテクチャではパッケージを流用せず、`ldd` の不足ライブラリを確認する。

```bash
mkdir -p .venv/browser-debs .venv/browser-libs
(
  cd .venv/browser-debs
  apt-get download libnspr4 libnss3 libasound2t64
)
for package in .venv/browser-debs/*.deb; do
  dpkg-deb -x "$package" .venv/browser-libs
done
```

今回取得したバージョンはlibnspr4 `2:4.35-1.1build1`、libnss3 `2:3.98-1ubuntu0.2`、libasound2t64 `1.2.11-1ubuntu0.3`。OS全体の設定変更・sudo・apt installは行っていない。シェル初期化ファイルも変更せず、ライブラリ探索パスはコマンドの環境に限って指定する。

### 実行

```bash
source .venv/bin/activate
PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/browsers" \
LD_LIBRARY_PATH="$PWD/.venv/browser-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
LISTING_SCREENSHOTS=/tmp/listing-screenshots \
timeout --signal=TERM --kill-after=5s 180s \
  python -m unittest tests.test_listing_browser -v
```

全体180秒で終了させる（TERMで終了しない場合は5秒後にKILL）。起動・個々の操作／待機は30秒。`timeout` の終了コード124は時間切れであり成功ではない。起動失敗・タイムアウト・テスト失敗は終了コード・エラー原文・失敗箇所を確認し、検証済みにしない。

サンドボックスがChromium起動に必要な操作を拒否する環境では、上記の環境変数設定とテスト実行だけに限定して制限外実行の承認を得る。恒久的な権限変更は不要。

ブラウザテストは全リクエストをfixtureで応答し、本番・外部情報源へ接続しない。WSLの日本語フォント不足を補うため、リポジトリ内のNoto Sans JP / Noto Serif JPをテストページだけへ読み込む。フォント追加配信やCSS上書きは本番HTMLには含めない。PNGは `/tmp/listing-screenshots` に保存する。

最終検証:

```bash
source .venv/bin/activate
PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/browsers" \
LD_LIBRARY_PATH="$PWD/.venv/browser-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
timeout --signal=TERM --kill-after=5s 180s \
  python -m unittest discover -s tests -v

PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/browsers" \
LD_LIBRARY_PATH="$PWD/.venv/browser-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
env -u FROM_DATE scripts/publish_manual_events.sh --dry-run

git diff --check
git status --short
```

publish dry-runは全テスト・テンプレート検証・Lambda ZIP作成（実行依存のbuildディレクトリへの導入）を行い、AWS更新はしない。ブラウザ実行およびビルド時のネットワークに必要な場合のみ、このdry-runコマンドに限定した承認を得る。

生成CLI（入力は公開判定済みpayload、取得・公開処理は実行しない）:

```bash
python scripts/generate_event_section.py --events public/events.json --output-dir /tmp/kendo-site
```

3ページとsitemapを生成する。従来の `--output /tmp/index.html` はトップ1ページ出力用として維持する。カテゴリページを試す際は生成先に共通events.jsonとpublicの画像等も配置し、HTTPサーバーのルートにする。

テンプレートの生成領域の同期（イベント・団体データは変更しない）:

```bash
python - <<'PY'
from pathlib import Path
from kendo_keiko.static_site import render_page_shell
path = Path('public/index.html')
path.write_text(render_page_shell(path.read_text(), 'all', 'https://kendo-keiko.com/'))
PY
```

## 生成・公開

Publisherと従来Lambdaハンドラーは共通の `publish_public_site` を使い、統合した1つのpayloadからJSON、3ページ、sitemapを生成する。ページごとにtitle・description・canonical・OGPを設定する。画像は既存OGPを共用する。共通データURLは `/events.json`、favicon等はルート相対パス。

S3出力キーは `events.json`, `index.html`, `keiko/index.html`, `renseikai/index.html`, `sitemap.xml` と既存アセット。`INDEX_KEY` はトップのみ変更でき、カテゴリキーは固定。`PUBLISH_INDEX_HTML=false` の場合は従来どおりJSONのみ公開。`EVENTS_KEY`を変更してもブラウザは `/events.json` を読むため、本サイトではデフォルト値を維持する。

ZIPには共通テンプレートとlisting.pyを含め、ビルド時にZIP用ディレクトリから3ページ生成を検証する。生成済みカテゴリHTMLをZIPへ固定同梱せず、Publisherの実行ごとに最新データで生成する。成功応答は既存フラグに加え `listing_pages_published=true` と `listing_page_keys` を返す。

公開スクリプトは成功フラグに加えて、S3原本events.jsonから再生成した3ページとS3のHTMLを比較する。定期公開と重なった場合は比較不一致を調査し、上書きして回避しない。

S3への複数ファイル公開はトランザクションではない。同一payloadから生成するが、公開途中・CloudFrontのTTL差では一時的な世代差があり得る。失敗時は原因を解消して再公開し、成功後に原本の一致を確認する。

初回適用は [CloudFrontカテゴリURL runbook](cloudfront-category-urls.md) と合わせる。merge・本番deployは個別の明示指示が必要。

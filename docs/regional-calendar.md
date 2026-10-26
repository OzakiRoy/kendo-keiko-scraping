# 地域ページと一覧／カレンダー

Issue #10・#59の初回試行として、関東と東京都の2ページを実装する。全ページへのカレンダー展開と、#59の埼玉・神奈川・千葉の独立ページは今回の完了範囲に含めない。

| 正規URL | 対象 |
| --- | --- |
| `/area/kanto/` | 東京都・神奈川県・埼玉県・千葉県・茨城県・栃木県・群馬県 |
| `/area/tokyo/` | 東京都 |

## 生成と表示

`merge_public_events`で公開対象を確定した共通payloadから、既存3ページと地域2ページを`render_listing_pages`で生成する。手動登録・自動取得を区別して除外しない。連盟稽古会も対象であり、Instagram週次Reelの連盟除外条件は変更しない。

対象地域は開催地の`area`から判定する。都県名で始まる値を受け入れ、複数都道府県を含む値や不明値を地域ページへ推測で割り当てない。団体所在地は判定に使わない。元の総合一覧は維持する。PythonとJSの判定を回帰テストする。

共通head・固定ロゴ・ヘッダー・「ご利用にあたって」は`public/index.html`から引き継ぐ。地域の本文は`kendo_keiko/templates/area.html`、生成処理は`kendo_keiko/regional.py`。初期HTMLに全対象カード、公式リンク、地域説明、掲載団体、件数、payloadの実際の更新日時と地域固有のメタ情報を含む。0件でもURLと他地域へのリンクを残す。

カレンダーは初期HTML内の`regional-data`を読み、静的カードを複製して表示する。日付・フィルタ処理は`calendar-core.js`、操作は`regional-calendar.js`、追加スタイルは`calendar.css`。静的一覧の元DOMを保持するため、JS無効／読込失敗時にも開催情報と公式リンクを利用できる。ページ表示時の新たなスクレイピング、API、アカウントは不要。ページと同じデータ世代を使うため、地域ページでは`events.json`の追加fetchは行わない。

PCの初期値は月表示、520px以下は土日比較。一覧／カレンダーを切り替えても期間・都県・会の種類・参加条件・団体・キーワードを保つ。月は月曜始まりで、同日多数は見出し2件＋残数を表示し、選択日詳細では省略しない。土日比較は両日を残し、0件の日を明示する。

基準日はブラウザで日本時間の当日を求める。日曜の「今週末」は前日の土曜と当日の日曜。日付算術はUTC上の年月日を使い、端末のタイムゾーンに依存させない。フィルタ解除は期間を保ち、「今月に戻る」で明示的に戻る。参加条件・申込必須・確認状況は既存の静的カードを再利用する。対象者等の公式補足も表示する。

## ローカル検証

既存の`.venv`と固定Playwright／Chromiumを使用する。導入・実行方法は[カテゴリ一覧](category-listings.md)を参照。

```bash
source .venv/bin/activate
PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/browsers" \
python -m unittest tests.test_regional_pages tests.test_regional_browser -v
node --check public/assets/calendar-core.js
node --check public/assets/regional-calendar.js
git diff --check
```

ブラウザテストはすべての通信をfixtureで応答し、GA4や本番サイトへ送信しない。320／390／768／1440px、JS無効・スクリプト失敗、フィルタと表示切替、同日多数、キーボード、公式リンクの計測を確認する。`REGIONAL_SCREENSHOTS`にディレクトリを指定すると確認用画面を出力できる。

生成CLIは5ページとsitemapを出力する。入力は公開判定済みのJSONとする。

```bash
python scripts/generate_event_section.py --events /path/to/public-events.json --output-dir /tmp/kendo-site
```

## 公開への組み込み

Lambda ZIPに地域テンプレート、生成モジュール、3つのカレンダーアセットを含む。生成済みの地域HTMLを固定同梱しない。公開順は共通CSS・写真・フォント→カレンダーCSS/JS→ツールCSS/JS→ツールHTML→地域2ページ→カテゴリ→トップ。sitemapにも地域2URLを追加する。

`scripts/publish_manual_events.sh`は地域の成功キーも確認し、公開S3原本の共通JSONから再生成した5ページを、配信HTMLと比較する。アセットと地域HTMLのMIME・短いキャッシュを維持する。S3公開はトランザクションではなく、公開中に一時的な世代差があり得る。

初回の本番適用は[CloudFront runbook](cloudfront-category-urls.md)の地域ページ追加手順を使う。S3へ置くだけでは`/area/.../`を配信できない。PRマージ・本番公開の指示後、地域HTMLと依存アセットを先に用意し、現在のFunctionを確認して地域URLの内部書き換えを適用・確認する。その後Publisherを更新して入口リンクを公開する。既存のカテゴリ処理や関連付けを未確認のまま上書きしない。

## 計測

既存のGA4タグを1回だけ引き継ぐ。初期表示・再描画では操作イベントを送らず、実際の操作時だけ以下を送る。キーワード等の入力内容や公式URLはイベントに付加しない。

| イベント | 操作 |
| --- | --- |
| `schedule_view_change` | 一覧／カレンダーを変更 |
| `schedule_period_change` | 月／土日・前後の期間を変更 |
| `schedule_day_select` | 別の日付を選択 |
| `event_source_click` | 開催カードの公式案内を開く |

共通パラメータは`area_page`（kanto/tokyo）、`view_mode`（list/calendar）、`period_mode`（month/weekend）。公式案内クリックには`event_type`も付ける。GA4の「管理→データの表示→カスタム定義」で、必要なパラメータをイベントスコープのカスタムディメンションとして登録する。イベント名がDebugViewに現れ、初期表示では操作イベントが発生しないことを本番で確認する。

公開後4週間は、Search Consoleで2URLのインデックス・表示・クリック・クエリを確認する。GA4では「地域ページ訪問セッションのうち、公式案内を開いたセッションの割合」を、流入元・曜日・掲載数と併せて見る。表示方式の選択は無作為ではないため、因果的なAB比較としない。クリックを実際の参加と同一視せず、主催者から任意で得られた参加事例も記録する。

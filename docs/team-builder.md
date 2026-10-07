# チーム分けツール運用ランブック

## 概要

`/tools/team-builder.html` は、参加者の入力をブラウザ内だけで処理する一時的なチーム編成ツールです。入力、編成結果、選手名・年齢・段位はサーバーへ送信せず、URL・タイトル・解析イベントにも含めません。

年齢・段位は編成の参考値であり、実力の均等や試合結果を保証しません。ページを離れると入力は失われます。編成結果はスクリーンショットまたはブラウザの印刷画面からPDFとして保存してください。

## 公開ファイル

- HTML: `public/tools/team-builder.html`
- CSS: `public/assets/team-builder.css`
- JavaScript: `public/assets/team-builder.js`
- URL: `https://kendo-keiko.com/tools/team-builder.html`

`scripts/build_lambda.sh` が3ファイルをLambda ZIPへ同梱し、PublisherがS3へ配置します。ツールのHTML・CSS・JSは `max-age=300`、既存のブランド画像は従来どおり `max-age=86400` です。イベント一覧の3ページとトップのリンクは、ツールファイルを先に配置してから公開されます。

## 検証

PRでは次を実行します。

```bash
node --check public/assets/team-builder.js
python -m unittest tests.test_team_builder -v
python -m unittest discover -s tests -v
env -u FROM_DATE scripts/publish_manual_events.sh --dry-run
```

実ブラウザで、初期サンプル、チーム数、年齢・段位の条件、人数差、手動交換、入力エラー、狭い画面、印刷メディア、離脱警告を確認します。Lambda ZIPには3ファイルと既存の公開資産が含まれ、開発用依存やブラウザは含まれません。

## 本番反映

merge後、最新mainのcleanなworktreeで通常の `scripts/publish_manual_events.sh --dry-run` を再確認してから、公開権限の明示指示に従ってPublisherを更新します。AWSのアカウント、Publisher設定、S3原本、CloudFrontの到達性は本番反映前に実確認し、未確認のまま設定変更しません。

本番後はS3原本で次を確認します。

- `tools/team-builder.html` が `text/html; charset=utf-8` かつ `max-age=300`
- `assets/team-builder.css` と `assets/team-builder.js` が `max-age=300`
- `/`, `/keiko/`, `/renseikai/` にチーム分けリンクがある
- `sitemap.xml` に `/tools/team-builder.html` がある
- ツールURLが200で、GA4・favicon・OGP・CSS・JSが同じ公開ホストから取得できる

イベントJSON、イベント一覧の分類・件数、既存ブランド画像はこの機能で変更しません。

## ロールバック

不具合時は、まずトップと3一覧のリンクを除いた直前のmainのLambda ZIPを作成し、Publisherだけを更新して同じ公開確認を行います。ツール用S3オブジェクトを手動削除したり、既存のイベントJSON・分類・CloudFront設定を推測で変更したりしません。必要なキャッシュ失効は、公開権限と既存CloudFront設定を確認したうえで対象パスだけに限定します。

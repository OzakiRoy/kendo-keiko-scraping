# 手動イベントの1コマンド公開ランブック

## 目的

`data/organizations.json` と `data/manual_events.json` の変更を、3つのLambda更新やStep Functionsの全体実行を行わず、安全に本番公開する。

公開時に更新するLambdaは `KendoKeikoPublisher` だけである。Publisherを明示的な `publish_only` モードで直接実行し、DynamoDBの既存自動イベントとLambda ZIP内の手動イベントを統合する。

## 前提

- データ変更がPRでレビューされ、`main` へマージ済みである
- `main` とupstreamが一致している
- AWS CLI、`jq`、`unzip`、`openssl` が利用できる
- AWS認証情報が設定済みである
- Publisher Lambdaに `EVENTS_BUCKET` が設定されている
- Lambda ZIPは `scripts/build_lambda.sh` で作成する

## 公開前のdry-run

作業ブランチ上で、データ検証、掲載団体セクション、全テスト、Lambda ZIP、ZIP内データを確認する。

```bash
scripts/publish_manual_events.sh \
  --organization-id kenen \
  --expected-count 1 \
  --dry-run
```

`--expected-count` は追加件数ではなく、JST当日以降に公開対象となる、その団体の `active` な手動イベント総数である。

基準日を固定して確認する場合:

```bash
scripts/publish_manual_events.sh \
  --organization-id kenen \
  --expected-count 1 \
  --from-date 2026-07-27 \
  --dry-run
```

掲載団体セクションに生成漏れがある場合、スクリプトは停止する。次を実行して変更をコミットする。

```bash
python scripts/generate_organization_section.py
git diff -- public/index.html
```

## 本番公開

PRをマージ後、最新の `main` から実行する。

```bash
git switch main
git pull --ff-only
git status --short --branch

scripts/publish_manual_events.sh \
  --organization-id kenen \
  --expected-count 1
```

スクリプトは次を順番に実行する。

1. `main`、upstreamとの一致、作業ツリーを確認
2. 団体・手動イベントJSONをモデルで検証
3. 手動イベントの団体IDが団体マスタに存在することを確認
4. 掲載団体セクションの生成漏れを確認
5. 全テストを実行
6. Lambda ZIPをビルド
7. ZIP内の団体・手動イベントデータを確認
8. AWSアカウント、リージョン、Publisher設定を表示
9. `KendoKeikoPublisher` だけを更新
10. ローカルZIPとLambdaの `CodeSha256` を比較
11. `publish_only=true` でPublisherを直接実行
12. `FunctionError` と公開フラグを確認
13. S3原本の `events.json` を取得して構造・必須メタデータ・団体別件数を確認

## Publisherへ渡すpayload

スクリプトは概ね次のpayloadを組み立てる。バケット名やキーはPublisherの環境変数から取得する。

```json
{
  "publish_only": true,
  "publish_to_s3": true,
  "publish_index_html": true,
  "region": "ap-northeast-1",
  "table_name": "KendoKeikoEvents",
  "from_date": "2026-07-27",
  "events_bucket": "<EVENTS_BUCKET>",
  "events_key": "events.json",
  "index_key": "index.html",
  "sitemap_key": "sitemap.xml",
  "site_url": "https://kendo-keiko.com/"
}
```

成功時のLambda応答には次が含まれる。

```json
{
  "mode": "publish_only",
  "s3_published": true,
  "index_published": true,
  "sitemap_published": true
}
```

## 更新される公開ファイル

PublisherはDynamoDBの自動イベントとZIP内の `data/manual_events.json` を統合し、公開用S3へ次を上書きする。

- `events.json`
- `index.html`
- `sitemap.xml`
- favicon、OGP画像、Web App Manifestなどの公開アセット

`index.html` はZIP内の `public/index.html` をテンプレートとして、統合後のイベントカードを静的生成した内容で更新する。

## 更新しないもの

手動イベント公開では次を更新・実行しない。

- `KendoKeikoListSources`
- `KendoKeikoScraperWorker`
- `KendoKeikoScraperWorkflow`
- 自動スクレイパー

定期実行の通常モードでは、従来どおり非空の `scrape_results` を必須とし、全情報源が失敗した場合は公開を停止する。

## 失敗時

スクリプトは異常を検知すると終了コード1で停止する。Publisher実行前の失敗では公開データは変更されない。

Lambdaコード更新後にPublisher実行が失敗した場合は、原因を確認して再実行する。コード自体を戻す必要がある場合は、直前の正常なLambdaバージョンまたはGitコミットからZIPを再作成してPublisherだけを更新する。

S3の公開結果確認ではCloudFrontではなく、まずS3原本の `events.json` を基準にする。CloudFrontの `index.html` はキャッシュが切れるまで以前の内容を返す場合がある。

# 基本SEO対応: 静的イベントHTML生成

## 目的

`events.json` をブラウザの JavaScript だけで描画する構成を残しつつ、同じイベント情報を `index.html` にも静的生成する。

これにより、次を実現する。

- 初期HTMLに開催予定の稽古会を含める
- JavaScriptを実行しないクローラーやブラウザにも内容を伝える
- `events.json` の取得失敗時も、直前に生成した稽古会一覧を表示する
- ホームページの `WebSite` 構造化データを追加する
- イベント更新時に `sitemap.xml` の `lastmod` も更新する

## 更新フロー

```text
EventBridge Scheduler
  ↓
Lambda: KendoKeikoScraper
  ↓
DynamoDB更新
  ↓
今日以降のイベントをDateIndexから取得
  ↓
S3へ同時発行
  ├─ events.json
  ├─ index.html（イベントカードを静的生成）
  └─ sitemap.xml（lastmodを更新）
```

`index.html` を手動デプロイ時だけ生成すると、イベント情報が古くなる。そこで既存の定期Lambdaから3ファイルをまとめて更新する。

## ローカル確認

```bash
python -m unittest discover -s tests -v
```

手元に `public/events.json` がある場合は、次のコマンドでも静的生成を確認できる。

```bash
python scripts/generate_event_section.py \
  --events public/events.json \
  --template public/index.html \
  --output /tmp/kendo-keiko-index.html
```

## Lambdaパッケージ作成

```bash
./scripts/build_lambda.sh
```

パッケージには以下も含まれる。

- `kendo_keiko/static_site.py`
- `public/index.html`

## Lambda更新

```bash
export AWS_REGION=ap-northeast-1
export FUNCTION_NAME=KendoKeikoScraper

aws lambda update-function-code \
  --function-name "${FUNCTION_NAME}" \
  --zip-file fileb://lambda_function.zip \
  --region "${AWS_REGION}"

aws lambda wait function-updated \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}"
```

## 環境変数

既存の環境変数を消さないよう、現在値を確認してからまとめて更新する。

```bash
aws lambda get-function-configuration \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Environment.Variables'
```

追加・確認する値:

```text
PUBLISH_TO_S3=true
PUBLISH_INDEX_HTML=true
EVENTS_BUCKET=<既存のサイト用S3バケット>
EVENTS_KEY=events.json
INDEX_KEY=index.html
SITEMAP_KEY=sitemap.xml
SITE_URL=https://kendo-keiko.com/
```

`PUBLISH_INDEX_HTML` 未指定時は、`PUBLISH_TO_S3=true` なら有効になる。ただし運用意図を明確にするため、明示設定を推奨する。

## 手動実行

```bash
aws lambda invoke \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/kendo-keiko-seo-result.json

cat /tmp/kendo-keiko-seo-result.json
```

レスポンスで次を確認する。

```text
s3_published: true
index_published: true
sitemap_published: true
```

## S3確認

```bash
aws s3api head-object \
  --bucket "${EVENTS_BUCKET}" \
  --key index.html

aws s3api head-object \
  --bucket "${EVENTS_BUCKET}" \
  --key sitemap.xml
```

初期HTMLにイベントが入っていることを確認する。

```bash
curl -s https://kendo-keiko.com/ | grep -E \
  'EVENT_CARDS_START|class="card"|application/ld\+json'
```

CloudFrontのキャッシュは最大5分を想定している。即時確認が必要な場合だけInvalidationする。

```bash
aws cloudfront create-invalidation \
  --distribution-id "${DISTRIBUTION_ID}" \
  --paths "/" "/index.html" "/sitemap.xml" "/events.json"
```

## Search Console確認

デプロイ後はURL検査でホームページを確認し、以下を見る。

- クロール済みページのHTMLに稽古会カードが含まれる
- canonicalが `https://kendo-keiko.com/` になっている
- sitemapが正常に取得される
- `WebSite` のサイト名情報がホームページにある

## 今回見送る項目

`Event` 構造化データはトップページの一覧に一括で付けず、個別イベントURLを作る段階で実装する。個別ページを用意した後、イベント名、開始日時、会場、公式情報への導線をページ単位でマークアップする。

また、`www.kendo-keiko.com` と `kendo-keiko.com` の301統一は、CloudFront Function等を使う別Issueとして扱う。

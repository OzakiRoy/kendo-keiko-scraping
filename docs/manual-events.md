# 手動イベント管理CLI

## 目的

自動取得の費用対効果が低い団体や、公式情報を人が確認した方が安全な稽古会を、Git管理のJSONへ登録する。

MVPでは次を正本とする。

```text
data/manual_events.json
```

手動イベントをDynamoDBへ複製しない。Publisher Lambdaが公開時に、DynamoDBの自動取得イベントと手動JSONを統合する。

## 前提

手動イベントを登録する団体は、先に `data/organizations.json` へ追加する。

手動専用団体の例:

```json
{
  "organization_id": "example",
  "name": "例示団体",
  "area": "埼玉県",
  "website_url": "https://example.com/",
  "source_type": "official_site",
  "scraper_type": "manual",
  "scraper_enabled": false,
  "event_type": "open_keiko"
}
```

`scraper_enabled: false` の団体は、Step Functionsの自動取得対象には含まれない。


## 新規手動団体を追加して本番公開する標準手順

新しい団体を手動掲載し、稽古予定を本番へ公開する場合は、次の順序で作業する。

### 1. 公式情報を確認する

登録前に、公式サイトや公式SNSで次の項目を確認する。

- 団体名
- 公式URL
- 開催日
- 開始・終了時刻
- 会場、住所、アクセス
- 参加条件
- 事前申込みの要否
- 参加費
- 中止・変更時の案内方法

確認した日時を `verified_at`、次回確認期限を `review_due_at` に設定する。

### 2. 作業ブランチを作る

```bash
git switch main
git pull --ff-only
git switch -c feature/add-manual-ORGANIZATION_ID-events
```

### 3. 団体マスタへ追加する

`data/organizations.json` に団体を追加する。

```json
{
  "organization_id": "example",
  "name": "例示団体",
  "area": "埼玉県",
  "website_url": "https://example.com/",
  "source_type": "official_site",
  "scraper_type": "manual",
  "scraper_enabled": false,
  "event_type": "open_keiko",
  "notes": "公式情報を管理者が確認し、手動登録",
  "public_description": "例示団体の稽古予定を掲載しています。"
}
```

`organization_id` は既存団体と重複しない、英小文字中心の安定したIDにする。

### 4. 掲載団体セクションを再生成する

```bash
python scripts/generate_organization_section.py
git diff -- public/index.html data/organizations.json
```

手動団体は `scraper_type: manual` により、`scraper_enabled: false` でも掲載団体一覧へ表示される。

### 5. イベントをdry-runする

同一内容で複数日開催する場合は `add-batch` を使う。

```bash
python manage_manual_events.py add-batch \
  --organization-id example \
  --date 2026-08-10 \
  --date 2026-08-17 \
  --date 2026-08-24 \
  --title "通常稽古" \
  --event-type open_keiko \
  --start-time 19:00 \
  --end-time 20:30 \
  --venue "例示武道館" \
  --area "埼玉県" \
  --address "埼玉県○○市○○" \
  --access "最寄駅から徒歩10分" \
  --fee "無料" \
  --application-required no \
  --source-url "https://example.com/schedule" \
  --participation-type anyone \
  --verified-at "2026-07-24T10:00:00+09:00" \
  --review-due-at 2026-08-24 \
  --note "参加前に公式情報を確認してください。" \
  --dry-run
```

出力された日付、曜日、時刻、会場、参加条件、確認期限を確認する。

### 6. 本登録する

内容に問題がなければ、同じコマンドから `--dry-run` を外して実行する。

```bash
python manage_manual_events.py add-batch \
  --organization-id example \
  --date 2026-08-10 \
  --date 2026-08-17 \
  --date 2026-08-24 \
  --title "通常稽古" \
  --event-type open_keiko \
  --start-time 19:00 \
  --end-time 20:30 \
  --venue "例示武道館" \
  --area "埼玉県" \
  --address "埼玉県○○市○○" \
  --access "最寄駅から徒歩10分" \
  --fee "無料" \
  --application-required no \
  --source-url "https://example.com/schedule" \
  --participation-type anyone \
  --verified-at "2026-07-24T10:00:00+09:00" \
  --review-due-at 2026-08-24 \
  --note "参加前に公式情報を確認してください。"
```

### 7. 登録結果を確認する

```bash
python manage_manual_events.py list \
  --organization-id example \
  --format json

python manage_manual_events.py list-review-due \
  --as-of 2026-08-24 \
  --format json

git diff -- data/manual_events.json
```

### 8. テストとLambdaビルドを実行する

```bash
python -m unittest discover -s tests -v
bash scripts/build_lambda.sh
```

`lambda_function.zip` に `data/manual_events.json` が含まれていることは、ビルドスクリプト内で検査される。

### 9. コミット、PR、マージを行う

```bash
git status
git diff --stat
git add data/organizations.json data/manual_events.json public/index.html tests/
git commit -m "feat: add example manual events"
git push -u origin HEAD
```

実際の変更ファイルがほかにもある場合は、`git status` を確認して追加する。PRには登録元、確認日時、登録日程、テスト結果を記載する。

マージ後は `main` を更新し、マージ後のソースからZIPを作り直す。

```bash
git switch main
git pull --ff-only
python -m unittest discover -s tests -v
bash scripts/build_lambda.sh
```

### 10. Lambdaへデプロイする

```bash
export AWS_REGION=ap-northeast-1

for FUNCTION_NAME in \
  KendoKeikoListSources \
  KendoKeikoScraperWorker \
  KendoKeikoPublisher
do
  aws lambda update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file fileb://lambda_function.zip \
    --region "${AWS_REGION}"

  aws lambda wait function-updated \
    --function-name "${FUNCTION_NAME}" \
    --region "${AWS_REGION}"
done
```

手動イベントの公開処理で直接使用するのはPublisherだが、3つのLambdaで同じZIPを使用しているため、運用上は3関数を同時に更新する。

### 11. Step Functionsを手動実行する

```bash
STATE_MACHINE_ARN=$(
  aws stepfunctions list-state-machines \
    --region "${AWS_REGION}" \
    --query "stateMachines[?name=='KendoKeikoScraperWorkflow'].stateMachineArn | [0]" \
    --output text
)

EXECUTION_ARN=$(
  aws stepfunctions start-execution \
    --state-machine-arn "${STATE_MACHINE_ARN}" \
    --name "manual-events-$(date +%Y%m%d-%H%M%S)" \
    --input '{"publish_to_s3":true,"debug":false}' \
    --region "${AWS_REGION}" \
    --query executionArn \
    --output text
)

echo "${EXECUTION_ARN}"
```

実行結果を確認する。

```bash
aws stepfunctions describe-execution \
  --execution-arn "${EXECUTION_ARN}" \
  --region "${AWS_REGION}" \
  --query '{status:status,output:output}' \
  --output json
```

`status` が `SUCCEEDED` であることを確認する。

### 12. 公開データを確認する

団体別の公開件数を確認する。

```bash
curl -fsS https://kendo-keiko.com/events.json \
  | jq '
      .events
      | group_by(.organization_id)
      | map({
          organization_id: .[0].organization_id,
          organization_name: .[0].organization_name,
          count: length
        })
    '
```

追加した団体のイベント内容を確認する。

```bash
curl -fsS https://kendo-keiko.com/events.json \
  | jq '[
      .events[]
      | select(.organization_id == "example")
      | {
          event_date,
          start_time,
          end_time,
          participation_type,
          update_mode,
          verified_at,
          review_due_at
        }
    ]'
```

公開イベントのメタデータ欠損がないことを確認する。

```bash
curl -fsS https://kendo-keiko.com/events.json \
  | jq '[
      .events[]
      | select(
          has("update_mode") == false
          or has("participation_type") == false
          or has("verified_at") == false
          or has("review_due_at") == false
        )
    ] | length'
```

結果が `0` なら正常。自動取得イベント数は取得日によって変動するため、公開イベントの合計件数を固定値で判定しない。

## 必須項目

手動登録時は以下を必須とする。

- 団体ID
- 開催日
- 公式URL
- タイムゾーン付きの確認日時 `verified_at`
- 次回確認期限 `review_due_at`

`update_mode` はCLIが `manual` を設定する。

## dry-run

登録・更新系コマンドには `--dry-run` を指定できる。JSONファイルを書き換えず、変更後のイベントと件数を表示する。

```bash
python manage_manual_events.py add \
  --organization-id example \
  --date 2026-08-10 \
  --title "合同稽古会" \
  --start-time 19:00 \
  --end-time 20:30 \
  --venue "例示武道館" \
  --source-url "https://example.com/events/20260810" \
  --participation-type contact_required \
  --verified-at "2026-07-24T10:00:00+09:00" \
  --review-due-at 2026-08-24 \
  --dry-run
```

## 1件登録

```bash
python manage_manual_events.py add \
  --organization-id example \
  --date 2026-08-10 \
  --title "合同稽古会" \
  --start-time 19:00 \
  --end-time 20:30 \
  --venue "例示武道館" \
  --source-url "https://example.com/events/20260810" \
  --participation-type contact_required \
  --verified-at "2026-07-24T10:00:00+09:00" \
  --review-due-at 2026-08-24
```

## 複数日付の一括登録

同じ内容で開催日だけが異なる場合は `add-batch` を使う。

```bash
python manage_manual_events.py add-batch \
  --organization-id example \
  --date 2026-08-10 \
  --date 2026-08-17 \
  --date 2026-08-24 \
  --title "通常稽古" \
  --start-time 19:00 \
  --end-time 20:30 \
  --venue "例示武道館" \
  --source-url "https://example.com/schedule" \
  --participation-type contact_required \
  --verified-at "2026-07-24T10:00:00+09:00" \
  --review-due-at 2026-08-24
```

## 一覧・詳細

```bash
python manage_manual_events.py list
python manage_manual_events.py list --status active
python manage_manual_events.py list --format json
python manage_manual_events.py show EVENT_ID
```

## 更新

イベントIDは登録後も維持する。開催日や開始時刻を変更した場合は、DateIndex用のキーだけを再生成する。

```bash
python manage_manual_events.py update EVENT_ID \
  --venue "変更後の会場" \
  --review-due-at 2026-09-01 \
  --dry-run
```

値を `null` に戻す場合:

```bash
python manage_manual_events.py update EVENT_ID \
  --clear-field fee \
  --clear-field access
```

## 中止・アーカイブ

```bash
python manage_manual_events.py cancel EVENT_ID --dry-run
python manage_manual_events.py archive EVENT_ID --dry-run
```

`cancelled` と `archived` はJSON上に記録を残すが、公開対象から除外する。同一日程の自動取得イベントが存在する場合も、手動レコードを優先して公開を抑止する。

## 再確認

確認日時を更新し、次の確認期限を設定する。

```bash
python manage_manual_events.py verify EVENT_ID \
  --review-due-at 2026-09-24
```

`--verified-at` を省略した場合は実行時のJST日時を使用する。

## 確認期限超過一覧

```bash
python manage_manual_events.py list-review-due
python manage_manual_events.py list-review-due --as-of 2026-08-24
python manage_manual_events.py list-review-due --format json
```

開催済み、`cancelled`、`archived` のイベントは確認対象から除外する。

## 公開パイプラインとの統合

Publisherは次の順序で公開イベントを作る。

```text
DynamoDBの自動取得イベント
  + data/manual_events.json
  ↓
開催日・団体・イベント種別・開始時刻・終了時刻で重複判定
  ↓
手動イベントを優先
  ↓
過去・中止・アーカイブを除外
  ↓
events.json / index.html / sitemap.xml
```

手動JSONを変更しただけでは、AWS上のPublisher Lambdaには反映されない。変更をコミットした後、Lambda ZIPを再作成・デプロイし、Step Functionsを実行して公開ファイルを更新する。

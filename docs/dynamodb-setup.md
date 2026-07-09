# DynamoDB セットアップ手順

## 目的

剣道オープン稽古会検索サービスのイベント情報を保存するため、DynamoDB テーブルを作成する。

MVP段階では、以下を満たす最小構成にする。

- 1イベントを `event_id` で一意に保存する
- 今日以降の稽古会を日付順に取得できるようにする
- キャパシティ管理を避けるため、オンデマンド課金にする
- 後から Terraform 化しやすいように、作成コマンドを明文化する

## 作成するリソース

```text
Table: KendoKeikoEvents

Primary key:
  event_id: String

GSI:
  IndexName: DateIndex
  Partition key: gsi1_pk: String
  Sort key: gsi1_sk: String

Billing mode:
  PAY_PER_REQUEST
```

## なぜこの設計にするか

### event_id

`event_id` はイベント1件を一意に識別するID。

例:

```text
kenbokukai-20260808-1300-a1b2c3d4
```

用途:

```text
イベント詳細を1件取得する
```

### DateIndex

トップページでは、全団体の「今日以降の稽古会」を日付順で表示したい。

そのため、日付順取得用に GSI を作成する。

```text
gsi1_pk = EVENT
gsi1_sk = 2026-08-08#13:00#kenbokukai#kenbokukai-20260808-1300-a1b2c3d4
```

用途:

```text
全団体の稽古会を日付順で取得する
```

MVPでは `gsi1_pk = EVENT` 固定でよい。

将来的にイベント数やアクセス数が増えた場合は、以下のように月単位などで分散することを検討する。

```text
gsi1_pk = EVENT#2026-08
```

## 前提

AWS CLI が設定済みであること。

確認:

```bash
aws --version
aws configure list
aws sts get-caller-identity
```

リージョンは東京リージョンを使う。

```bash
export AWS_REGION=ap-northeast-1
export TABLE_NAME=KendoKeikoEvents
```

必要に応じて profile を指定する。

```bash
export AWS_PROFILE=your-profile-name
```

## 1. DynamoDB テーブルを作成する

```bash
aws dynamodb create-table \
  --table-name "${TABLE_NAME}" \
  --attribute-definitions \
    AttributeName=event_id,AttributeType=S \
    AttributeName=gsi1_pk,AttributeType=S \
    AttributeName=gsi1_sk,AttributeType=S \
  --key-schema \
    AttributeName=event_id,KeyType=HASH \
  --global-secondary-indexes '[
    {
      "IndexName": "DateIndex",
      "KeySchema": [
        {"AttributeName": "gsi1_pk", "KeyType": "HASH"},
        {"AttributeName": "gsi1_sk", "KeyType": "RANGE"}
      ],
      "Projection": {
        "ProjectionType": "ALL"
      }
    }
  ]' \
  --billing-mode PAY_PER_REQUEST \
  --region "${AWS_REGION}"
```

## 2. テーブル作成完了を待つ

```bash
aws dynamodb wait table-exists \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}"
```

## 3. テーブルを確認する

```bash
aws dynamodb describe-table \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}"
```

テーブル状態だけ確認する場合:

```bash
aws dynamodb describe-table \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Table.{TableName:TableName,TableStatus:TableStatus,BillingMode:BillingModeSummary.BillingMode,ItemCount:ItemCount}'
```

GSI を確認する場合:

```bash
aws dynamodb describe-table \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Table.GlobalSecondaryIndexes[].{IndexName:IndexName,IndexStatus:IndexStatus,KeySchema:KeySchema,Projection:Projection}'
```

## 4. テストデータを1件登録する

```bash
aws dynamodb put-item \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}" \
  --item '{
    "event_id": {"S": "test-20260808-1300"},
    "organization_id": {"S": "kenbokukai"},
    "organization_name": {"S": "剣睦会"},
    "event_type": {"S": "open_keiko"},
    "event_date": {"S": "2026-08-08"},
    "weekday": {"S": "土"},
    "start_time": {"S": "13:00"},
    "end_time": {"S": "17:00"},
    "venue": {"S": "江戸川区スポーツセンター1階"},
    "area": {"S": "東京都"},
    "source_url": {"S": "https://kenbokukai.com/"},
    "source_type": {"S": "official_site"},
    "status": {"S": "active"},
    "last_scraped_at": {"S": "2026-07-09T10:00:00+09:00"},
    "gsi1_pk": {"S": "EVENT"},
    "gsi1_sk": {"S": "2026-08-08#13:00#kenbokukai#test-20260808-1300"}
  }'
```

## 5. event_id で1件取得する

```bash
aws dynamodb get-item \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}" \
  --key '{
    "event_id": {"S": "test-20260808-1300"}
  }'
```

## 6. DateIndex で日付順に取得する

全団体のイベントを日付順で取得する。

```bash
aws dynamodb query \
  --table-name "${TABLE_NAME}" \
  --index-name DateIndex \
  --region "${AWS_REGION}" \
  --key-condition-expression 'gsi1_pk = :pk' \
  --expression-attribute-values '{
    ":pk": {"S": "EVENT"}
  }'
```

今日以降のイベントを取得する場合は、`gsi1_sk` に対して範囲条件を付ける。

例: 2026-07-09以降

```bash
aws dynamodb query \
  --table-name "${TABLE_NAME}" \
  --index-name DateIndex \
  --region "${AWS_REGION}" \
  --key-condition-expression 'gsi1_pk = :pk AND gsi1_sk >= :from_date' \
  --expression-attribute-values '{
    ":pk": {"S": "EVENT"},
    ":from_date": {"S": "2026-07-09"}
  }'
```

## 7. テストデータを削除する

```bash
aws dynamodb delete-item \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}" \
  --key '{
    "event_id": {"S": "test-20260808-1300"}
  }'
```

## 8. テーブルを削除する場合

MVP検証で作り直したい場合だけ実行する。

```bash
aws dynamodb delete-table \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}"
```

削除完了を待つ。

```bash
aws dynamodb wait table-not-exists \
  --table-name "${TABLE_NAME}" \
  --region "${AWS_REGION}"
```

## export_events.py との対応

今後 `export_events.py` から DynamoDB に保存する場合、各イベントに以下の属性を持たせる。

```text
event_id
organization_id
organization_name
event_type
event_date
weekday
start_time
end_time
venue
area
address
access
fee
application_required
source_url
source_type
last_scraped_at
status
raw_note
gsi1_pk
gsi1_sk
```

DynamoDB 保存用のキーは以下。

```text
event_id = 一意なイベントID
gsi1_pk = EVENT
gsi1_sk = event_date#start_time#organization_id#event_id
```

例:

```text
event_id = kenbokukai-20260808-1300-a1b2c3d4
gsi1_pk = EVENT
gsi1_sk = 2026-08-08#13:00#kenbokukai#kenbokukai-20260808-1300-a1b2c3d4
```

## 次の改善候補

### OrganizationDateIndex

団体別ページを高速に表示したくなったら追加する。

```text
IndexName: OrganizationDateIndex
Partition key: organization_id
Sort key: event_date_start
```

用途:

```text
剣睦会の今後の稽古だけ表示する
```

### AreaDateIndex

地域別ページを作る段階で検討する。

```text
IndexName: AreaDateIndex
Partition key: area
Sort key: event_date_start
```

用途:

```text
東京都の今後の稽古だけ表示する
```

## 現時点の方針

MVPでは以下で進める。

```text
Primary key:
  event_id

GSI:
  DateIndex

Billing:
  PAY_PER_REQUEST
```

Terraform 化は、DynamoDB 書き込みと Lambda 実行まで確認できてから行う。

# S3 events.json エクスポート手順

## 目的

Lambda 実行時に DynamoDB を更新したあと、DynamoDB の `DateIndex` から今日以降の稽古会を取得し、表示用の `events.json` を S3 に配置する。

MVPでは、以下の構成にする。

```text
EventBridge Scheduler
  ↓
Lambda: KendoKeikoScraper
  ↓
スクレイピング
  ↓
DynamoDB: KendoKeikoEvents
  ↓
DynamoDB DateIndex から今日以降を取得
  ↓
S3: events.json
```

## 方針

- DynamoDB を正式なデータ保存先とする
- S3 の `events.json` はフロント表示用キャッシュとして扱う
- フロントエンドは将来的に `fetch("./events.json")` で読み込む
- ブラウザから DynamoDB を直接読ませない

## 1. 変数を設定する

```bash
export AWS_REGION=ap-northeast-1
export TABLE_NAME=KendoKeikoEvents
export FUNCTION_NAME=KendoKeikoScraper

export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export EVENTS_BUCKET="kendo-keiko-site-${ACCOUNT_ID}-${AWS_REGION}"
export EVENTS_KEY="events.json"

export LAMBDA_ROLE_NAME=KendoKeikoScrapeLambdaRole
```

必要に応じて AWS profile を指定する。

```bash
export AWS_PROFILE=your-profile-name
```

## 2. S3バケットを作成する

東京リージョンに作成するため、`LocationConstraint` を指定する。

```bash
aws s3api create-bucket \
  --bucket "${EVENTS_BUCKET}" \
  --region "${AWS_REGION}" \
  --create-bucket-configuration LocationConstraint="${AWS_REGION}"
```

## 3. Block Public Access を有効にする

MVPでは S3 を直接公開しない。後で CloudFront OAC 経由で配信する。

```bash
aws s3api put-public-access-block \
  --bucket "${EVENTS_BUCKET}" \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

確認する。

```bash
aws s3api get-public-access-block \
  --bucket "${EVENTS_BUCKET}"
```

## 4. サーバー側暗号化を有効にする

```bash
aws s3api put-bucket-encryption \
  --bucket "${EVENTS_BUCKET}" \
  --server-side-encryption-configuration '{
    "Rules": [
      {
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "AES256"
        }
      }
    ]
  }'
```

## 5. Lambda実行ロールに S3 PutObject 権限を追加する

Lambda が `events.json` を配置できるようにする。

```bash
cat > lambda-s3-putobject-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::${EVENTS_BUCKET}/*"
    }
  ]
}
EOF
```

```bash
aws iam put-role-policy \
  --role-name "${LAMBDA_ROLE_NAME}" \
  --policy-name KendoKeikoS3PutObjectPolicy \
  --policy-document file://lambda-s3-putobject-policy.json
```

IAM反映を少し待つ。

```bash
sleep 10
```

## 6. lambda_function.py を差し替える

`lambda_function.py` をS3エクスポート対応版に置き換える。

```bash
cp ~/Downloads/lambda_function.py ./lambda_function.py
```

## 7. Lambdaデプロイzipを再作成する

```bash
rm -rf build/lambda lambda_function.zip
mkdir -p build/lambda

python -m pip install -r requirements.txt -t build/lambda

cp export_events.py scrape_kendo_schedule.py lambda_function.py build/lambda/

mkdir -p build/lambda/data
cp data/organizations.json build/lambda/data/organizations.json

cd build/lambda
zip -r ../../lambda_function.zip .
cd ../..
```

## 8. Lambdaコードを更新する

```bash
aws lambda update-function-code \
  --function-name "${FUNCTION_NAME}" \
  --zip-file fileb://lambda_function.zip \
  --region "${AWS_REGION}"
```

更新完了を待つ。

```bash
aws lambda wait function-updated \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}"
```

## 9. Lambda環境変数を更新する

注意: `update-function-configuration --environment` は環境変数セットを更新するため、必要な変数をまとめて指定する。

```bash
aws lambda update-function-configuration \
  --function-name "${FUNCTION_NAME}" \
  --environment "Variables={TABLE_NAME=${TABLE_NAME},GROUP=all,DEBUG=true,PUBLISH_TO_S3=true,EVENTS_BUCKET=${EVENTS_BUCKET},EVENTS_KEY=${EVENTS_KEY}}" \
  --region "${AWS_REGION}"
```

更新完了を待つ。

```bash
aws lambda wait function-updated \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}"
```

## 10. Lambdaを手動実行する

```bash
aws lambda invoke \
  --function-name "${FUNCTION_NAME}" \
  --payload '{"group":"all","debug":true,"publish_to_s3":true}' \
  --cli-binary-format raw-in-base64-out \
  --region "${AWS_REGION}" \
  /tmp/kendo-lambda-output.json

cat /tmp/kendo-lambda-output.json
```

## 11. CloudWatch Logs を確認する

```bash
aws logs tail "/aws/lambda/${FUNCTION_NAME}" \
  --since 10m \
  --region "${AWS_REGION}"
```

以下のようなログが出ていればよい。

```text
kendo scraper started
saved ... events to DynamoDB table KendoKeikoEvents
events.json uploaded to S3
```

## 12. S3にevents.jsonが置かれたか確認する

```bash
aws s3api head-object \
  --bucket "${EVENTS_BUCKET}" \
  --key "${EVENTS_KEY}"
```

内容を確認する。

```bash
aws s3 cp "s3://${EVENTS_BUCKET}/${EVENTS_KEY}" - | jq '.event_count'
```

`jq` がない場合。

```bash
aws s3 cp "s3://${EVENTS_BUCKET}/${EVENTS_KEY}" - | head -40
```

## 13. EventBridge Scheduler 経由の動作を確認する

Scheduler は既存の Lambda を呼ぶだけなので、環境変数 `PUBLISH_TO_S3=true` が設定されていれば、次回の定期実行から S3 へも出力される。

即時確認したい場合は、一時スケジュールを作るか、Lambda手動実行で確認する。

## 14. Gitに残さない一時ファイル

以下はGit管理しない。

```text
lambda-s3-putobject-policy.json
build/
lambda_function.zip
```

`.gitignore` に追加する。

```bash
cat >> .gitignore <<'EOF'

# local AWS S3 export policy files
lambda-s3-putobject-policy.json
EOF
```


## 15. DateIndex Query 権限を追加する

S3用の `events.json` は、DynamoDB の `DateIndex` を Query して生成する。

そのため、Lambda実行ロールには `dynamodb:Query` 権限も必要。

```bash
export AWS_REGION=ap-northeast-1
export TABLE_NAME=KendoKeikoEvents
export LAMBDA_ROLE_NAME=KendoKeikoScrapeLambdaRole
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

cat > lambda-dynamodb-query-index-policy.json <<EOF2
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "QueryKendoKeikoEventsDateIndex",
      "Effect": "Allow",
      "Action": [
        "dynamodb:Query"
      ],
      "Resource": [
        "arn:aws:dynamodb:${AWS_REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}",
        "arn:aws:dynamodb:${AWS_REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}/index/DateIndex"
      ]
    }
  ]
}
EOF2

aws iam put-role-policy \
  --role-name "${LAMBDA_ROLE_NAME}" \
  --policy-name KendoKeikoDynamoDBQueryDateIndexPolicy \
  --policy-document file://lambda-dynamodb-query-index-policy.json

```


## 16. Gitに記録する

```bash
git add lambda_function.py docs/s3-events-export-setup.md .gitignore
git commit -m "Add S3 export for events JSON"
git push
```

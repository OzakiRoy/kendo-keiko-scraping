# Lambda デプロイ手順（AWS CLI）

## 目的

ローカルで動いている `export_events.py --storage dynamodb` を AWS Lambda で手動実行できるようにする。

この段階では Terraform は使わない。まず以下を確認する。

```text
Lambda 手動実行
  ↓
スクレイピング
  ↓
DynamoDB 更新
  ↓
CloudWatch Logs 確認
```

## 方針

- Lambda は VPC に入れない
- ランタイムは `python3.12`
- ハンドラーは `lambda_function.lambda_handler`
- `lambda_function.py` は `export_events.py` の `main()` を呼ぶ薄いラッパーにする
- `data/organizations.json` を zip に含める
- `requests` / `beautifulsoup4` / `boto3` などの依存ライブラリは zip に含める

## 0. 前提

リポジトリ直下で作業する。

```bash
pwd
ls
```

以下が存在すること。

```text
export_events.py
scrape_kendo_schedule.py
data/organizations.json
requirements.txt
lambda_function.py
```

AWS CLI の認証確認。

```bash
aws sts get-caller-identity
```

変数を設定する。

```bash
export AWS_REGION=ap-northeast-1
export TABLE_NAME=KendoKeikoEvents
export FUNCTION_NAME=KendoKeikoScraper
export ROLE_NAME=KendoKeikoScrapeLambdaRole
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
```

## 1. lambda_function.py を配置する

リポジトリ直下に配置する。

```bash
cp ~/Downloads/lambda_function.py ./lambda_function.py
```

ローカルで構文確認する。

```bash
python -m py_compile lambda_function.py
```

## 2. Lambda 実行ロールを作る

信頼ポリシーを作る。

```bash
cat > lambda-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
```

ロールを作る。

```bash
aws iam create-role \
  --role-name "${ROLE_NAME}" \
  --assume-role-policy-document file://lambda-trust-policy.json
```

CloudWatch Logs 用の AWS 管理ポリシーを付与する。

```bash
aws iam attach-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

DynamoDB 書き込み用のインラインポリシーを作る。

```bash
cat > lambda-dynamodb-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:BatchWriteItem",
        "dynamodb:PutItem",
        "dynamodb:DescribeTable"
      ],
      "Resource": "arn:aws:dynamodb:${AWS_REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
    }
  ]
}
EOF
```

ポリシーを付与する。

```bash
aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name KendoKeikoDynamoDBWritePolicy \
  --policy-document file://lambda-dynamodb-policy.json
```

IAM 反映待ち。

```bash
sleep 10
```

## 3. デプロイ zip を作る

ビルドディレクトリを作る。

```bash
rm -rf build/lambda lambda_function.zip
mkdir -p build/lambda
```

依存ライブラリを配置する。

```bash
python -m pip install -r requirements.txt -t build/lambda
```

アプリコードと団体マスタを配置する。

```bash
cp export_events.py scrape_kendo_schedule.py lambda_function.py build/lambda/
mkdir -p build/lambda/data
cp data/organizations.json build/lambda/data/organizations.json
```

zip を作る。

```bash
cd build/lambda
zip -r ../../lambda_function.zip .
cd ../..
```

zip の中身を確認する。

```bash
unzip -l lambda_function.zip | head -50
```

最低限、以下が含まれていればよい。

```text
lambda_function.py
export_events.py
scrape_kendo_schedule.py
data/organizations.json
requests/
bs4/
```

## 4. Lambda 関数を作成する

```bash
aws lambda create-function \
  --function-name "${FUNCTION_NAME}" \
  --runtime python3.12 \
  --role "${ROLE_ARN}" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lambda_function.zip \
  --timeout 300 \
  --memory-size 512 \
  --environment "Variables={TABLE_NAME=${TABLE_NAME},GROUP=all,DEBUG=true}" \
  --region "${AWS_REGION}"
```

作成確認。

```bash
aws lambda get-function \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Configuration.{FunctionName:FunctionName,Runtime:Runtime,Handler:Handler,Timeout:Timeout,MemorySize:MemorySize,State:State}'
```

## 5. Lambda を手動実行する

全団体で実行する。

```bash
aws lambda invoke \
  --function-name "${FUNCTION_NAME}" \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  --region "${AWS_REGION}" \
  /tmp/kendo-lambda-output.json

cat /tmp/kendo-lambda-output.json
```

剣睦会だけで実行する場合。

```bash
aws lambda invoke \
  --function-name "${FUNCTION_NAME}" \
  --payload '{"group":"kenbokukai","debug":true}' \
  --cli-binary-format raw-in-base64-out \
  --region "${AWS_REGION}" \
  /tmp/kendo-lambda-output.json

cat /tmp/kendo-lambda-output.json
```

## 6. CloudWatch Logs を確認する

```bash
aws logs tail "/aws/lambda/${FUNCTION_NAME}" \
  --since 10m \
  --region "${AWS_REGION}"
```

ログ保持期間を14日にする。

```bash
aws logs put-retention-policy \
  --log-group-name "/aws/lambda/${FUNCTION_NAME}" \
  --retention-in-days 14 \
  --region "${AWS_REGION}"
```

## 7. DynamoDB 更新を確認する

```bash
aws dynamodb query \
  --table-name "${TABLE_NAME}" \
  --index-name DateIndex \
  --region "${AWS_REGION}" \
  --key-condition-expression 'gsi1_pk = :pk' \
  --expression-attribute-values '{
    ":pk": {"S": "EVENT"}
  }' \
  --query 'Items[].{date:event_date.S,time:start_time.S,org:organization_name.S,venue:venue.S,event_id:event_id.S}'
```

## 8. コード更新時の再デプロイ

コードを修正したら zip を作り直す。

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

Lambda のコードを更新する。

```bash
aws lambda update-function-code \
  --function-name "${FUNCTION_NAME}" \
  --zip-file fileb://lambda_function.zip \
  --region "${AWS_REGION}"
```

環境変数やタイムアウトを変える場合。

```bash
aws lambda update-function-configuration \
  --function-name "${FUNCTION_NAME}" \
  --timeout 300 \
  --memory-size 512 \
  --environment "Variables={TABLE_NAME=${TABLE_NAME},GROUP=all,DEBUG=true}" \
  --region "${AWS_REGION}"
```

## 9. Git管理

管理する。

```text
lambda_function.py
docs/lambda-cli-deploy.md
```

管理しない。

```text
lambda_function.zip
build/
lambda-trust-policy.json
lambda-dynamodb-policy.json
```

`.gitignore` に追加する。

```text
build/
lambda_function.zip
lambda-trust-policy.json
lambda-dynamodb-policy.json
```

コミット例。

```bash
git add lambda_function.py docs/lambda-cli-deploy.md .gitignore
git commit -m "Add Lambda scrape job deployment"
git push
```

## 次の段階

Lambda 手動実行で以下が確認できたら、次は EventBridge Scheduler で定期実行する。

```text
Lambda 手動実行 OK
CloudWatch Logs OK
DynamoDB 更新 OK
```

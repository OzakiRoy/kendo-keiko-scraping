# EventBridge Scheduler セットアップ手順

## 目的

`KendoKeikoScraper` Lambda を EventBridge Scheduler で定期実行し、DynamoDB の `KendoKeikoEvents` を自動更新する。

MVP段階では、以下の構成にする。

```text
毎朝 05:00 JST
  ↓
EventBridge Scheduler
  ↓
Lambda: KendoKeikoScraper
  ↓
スクレイピング
  ↓
DynamoDB: KendoKeikoEvents
  ↓
CloudWatch Logs
```

## 前提

以下が作成済みであること。

- DynamoDB テーブル: `KendoKeikoEvents`
- Lambda 関数: `KendoKeikoScraper`
- Lambda が DynamoDB に書き込める IAM ロール
- Lambda の手動実行で DynamoDB 更新が確認済み
- CloudWatch Logs に Lambda 実行ログが出ることを確認済み

## 1. 変数を設定する

```bash
export AWS_REGION=ap-northeast-1
export FUNCTION_NAME=KendoKeikoScraper
export SCHEDULE_NAME=KendoKeikoScraperDaily
export SCHEDULER_ROLE_NAME=KendoKeikoSchedulerInvokeLambdaRole

export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export FUNCTION_ARN="arn:aws:lambda:${AWS_REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
export SCHEDULER_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${SCHEDULER_ROLE_NAME}"
```

必要に応じて AWS profile を指定する。

```bash
export AWS_PROFILE=your-profile-name
```

## 2. Scheduler 用 IAM ロールの信頼ポリシーを作成する

EventBridge Scheduler が IAM ロールを AssumeRole できるようにする。

```bash
cat > scheduler-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "scheduler.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
```

## 3. Scheduler 用 IAM ロールを作成する

```bash
aws iam create-role \
  --role-name "${SCHEDULER_ROLE_NAME}" \
  --assume-role-policy-document file://scheduler-trust-policy.json
```

## 4. Lambda Invoke 権限ポリシーを作成する

Scheduler が `KendoKeikoScraper` を実行できるようにする。

```bash
cat > scheduler-lambda-invoke-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "lambda:InvokeFunction"
      ],
      "Resource": "${FUNCTION_ARN}"
    }
  ]
}
EOF
```

## 5. Scheduler 用 IAM ロールに権限を付与する

```bash
aws iam put-role-policy \
  --role-name "${SCHEDULER_ROLE_NAME}" \
  --policy-name KendoKeikoSchedulerInvokeLambdaPolicy \
  --policy-document file://scheduler-lambda-invoke-policy.json
```

IAM の反映を少し待つ。

```bash
sleep 10
```

## 6. 毎朝 05:00 JST のスケジュールを作成する

```bash
aws scheduler create-schedule \
  --name "${SCHEDULE_NAME}" \
  --schedule-expression 'cron(0 5 * * ? *)' \
  --schedule-expression-timezone 'Asia/Tokyo' \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target "{
    \"Arn\": \"${FUNCTION_ARN}\",
    \"RoleArn\": \"${SCHEDULER_ROLE_ARN}\",
    \"Input\": \"{\\\"group\\\":\\\"all\\\",\\\"debug\\\":true}\"
  }" \
  --region "${AWS_REGION}"
```

この設定で、毎日 05:00 JST に Lambda が実行される。

## 7. スケジュールを確認する

```bash
aws scheduler get-schedule \
  --name "${SCHEDULE_NAME}" \
  --region "${AWS_REGION}"
```

必要な情報だけ見る場合。

```bash
aws scheduler get-schedule \
  --name "${SCHEDULE_NAME}" \
  --region "${AWS_REGION}" \
  --query '{Name:Name,State:State,ScheduleExpression:ScheduleExpression,Timezone:ScheduleExpressionTimezone,Target:Target.Arn}'
```

`State` が `ENABLED` であれば有効。

## 8. 動作確認用の一時スケジュールを作る場合

翌朝まで待たずに Scheduler 経由の実行を確認したい場合は、5分おきの一時スケジュールを作る。

```bash
export TEST_SCHEDULE_NAME=KendoKeikoScraperTestEvery5Min

aws scheduler create-schedule \
  --name "${TEST_SCHEDULE_NAME}" \
  --schedule-expression 'rate(5 minutes)' \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target "{
    \"Arn\": \"${FUNCTION_ARN}\",
    \"RoleArn\": \"${SCHEDULER_ROLE_ARN}\",
    \"Input\": \"{\\\"group\\\":\\\"all\\\",\\\"debug\\\":true}\"
  }" \
  --region "${AWS_REGION}"
```

5〜6分待って CloudWatch Logs を確認する。

```bash
aws logs tail "/aws/lambda/${FUNCTION_NAME}" \
  --since 10m \
  --region "${AWS_REGION}"
```

確認できたら一時スケジュールは削除する。

```bash
aws scheduler delete-schedule \
  --name "${TEST_SCHEDULE_NAME}" \
  --region "${AWS_REGION}"
```

## 9. CloudWatch Logs を確認する

```bash
aws logs tail "/aws/lambda/${FUNCTION_NAME}" \
  --since 10m \
  --region "${AWS_REGION}"
```

定期実行後に、以下のようなログが出ていればよい。

```text
START RequestId: ...
[DEBUG] ...
saved ... events to DynamoDB table KendoKeikoEvents
END RequestId: ...
REPORT RequestId: ...
```

## 10. DynamoDB 更新を確認する

```bash
aws dynamodb query \
  --table-name KendoKeikoEvents \
  --index-name DateIndex \
  --region "${AWS_REGION}" \
  --key-condition-expression 'gsi1_pk = :pk' \
  --expression-attribute-values '{
    ":pk": {"S": "EVENT"}
  }' \
  --query 'Items[].{date:event_date.S,time:start_time.S,org:organization_name.S,venue:venue.S,event_id:event_id.S,last:last_scraped_at.S}'
```

`last_scraped_at` が Scheduler 実行後の時刻に更新されていればOK。

## 11. スケジュールを一時停止する場合

```bash
aws scheduler update-schedule \
  --name "${SCHEDULE_NAME}" \
  --schedule-expression 'cron(0 5 * * ? *)' \
  --schedule-expression-timezone 'Asia/Tokyo' \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target "{
    \"Arn\": \"${FUNCTION_ARN}\",
    \"RoleArn\": \"${SCHEDULER_ROLE_ARN}\",
    \"Input\": \"{\\\"group\\\":\\\"all\\\",\\\"debug\\\":true}\"
  }" \
  --state DISABLED \
  --region "${AWS_REGION}"
```

## 12. スケジュールを再開する場合

```bash
aws scheduler update-schedule \
  --name "${SCHEDULE_NAME}" \
  --schedule-expression 'cron(0 5 * * ? *)' \
  --schedule-expression-timezone 'Asia/Tokyo' \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target "{
    \"Arn\": \"${FUNCTION_ARN}\",
    \"RoleArn\": \"${SCHEDULER_ROLE_ARN}\",
    \"Input\": \"{\\\"group\\\":\\\"all\\\",\\\"debug\\\":true}\"
  }" \
  --state ENABLED \
  --region "${AWS_REGION}"
```

## 13. スケジュールを削除する場合

```bash
aws scheduler delete-schedule \
  --name "${SCHEDULE_NAME}" \
  --region "${AWS_REGION}"
```

## 14. 一時ファイルの扱い

以下のファイルはローカル作業用のため、Git管理しない。

```text
scheduler-trust-policy.json
scheduler-lambda-invoke-policy.json
```

`.gitignore` に追加する。

```bash
cat >> .gitignore <<'EOF'

# local AWS scheduler policy files
scheduler-trust-policy.json
scheduler-lambda-invoke-policy.json
EOF
```

## 15. Git に記録する

この手順書は Git 管理する。

```bash
git add docs/eventbridge-scheduler-setup.md .gitignore
git commit -m "Add EventBridge Scheduler setup guide"
git push
```

## 現時点の方針

MVPでは以下の構成で運用する。

```text
EventBridge Scheduler
  ↓
Lambda
  ↓
DynamoDB
  ↓
CloudWatch Logs
```

Terraform 化は、DynamoDB / Lambda / EventBridge Scheduler の手動構築と動作確認が完了してから行う。

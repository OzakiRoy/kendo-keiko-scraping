# アーキテクチャ

## 初期MVP

```text
Route 53
  ↓
CloudFront
  ├─ AWS WAF
  ├─ S3 frontend
  └─ API Gateway
        ↓
      Lambda
        ↓
      DynamoDB
```

## スクレイピング定期実行

初期:

```text
EventBridge Scheduler
  ↓
Lambda scrape_job
  ↓
DynamoDB
```

対象団体が増えたり、headless browser が必要になった場合:

```text
EventBridge Scheduler
  ↓
ECS Fargate Scheduled Task
  ↓
DynamoDB
```

## 方針

- ユーザーアクセスごとにスクレイピングしない
- 定期実行で取得し、DBへ保存する
- 画面/APIはDBを見る
- 公式URLと最終取得日時を必ず表示する
- WAF / CSPM / Prowler の実験台として運用する

# Step Functionsによるスクレイパー実行管理

## 目的

団体ごとのスクレイパーを独立して実行し、1団体の失敗で全体を停止させず、成功・0件警告・失敗を確認できるようにする。

## 構成

```text
EventBridge Scheduler
  ↓
Step Functions Standard Workflow
  ├─ ListSources Lambda
  ├─ Inline Map（MaxConcurrency: 2）
  │    └─ ScraperWorker Lambda × 情報源
  └─ Publisher Lambda
       ├─ events.json
       ├─ index.html
       └─ sitemap.xml
```

同じZIPパッケージを3つのLambda関数へデプロイし、Handlerだけを分ける。

| 責務 | Handler |
|---|---|
| 有効な取得元を列挙 | `list_sources_handler.lambda_handler` |
| 1団体を取得してDynamoDBへ保存 | `scraper_worker_handler.lambda_handler` |
| 公開ファイルを生成 | `publisher_handler.lambda_handler` |

既存の `lambda_function.lambda_handler` は、本番切り替えとロールバック確認が終わるまで残す。

## workerの結果

```json
{
  "run_id": "example-run",
  "organization_id": "tokyo",
  "scraper_type": "tokyo",
  "status": "success",
  "event_count": 9,
  "duration_ms": 1200,
  "checked_at": "2026-07-22T17:00:00+09:00",
  "from_date": "2026-07-22",
  "error_type": null,
  "error_message": null
}
```

未来イベントが0件の場合は `warning` と `empty_result` を返す。例外はLambdaエラーとして再送出し、Step FunctionsのRetryとCatchで処理する。

## 失敗時の扱い

- 一時的なLambdaサービスエラーはStep Functionsが再試行する
- `requests.RequestException` は `ScraperTransientError` に変換し再試行する
- 最終失敗はMap内で `failure` 結果へ変換する
- 一部失敗でもPublisherを実行し、失敗した団体の既存DynamoDBデータは維持する
- 全団体が `failure` の場合はPublisherが失敗し、公開を行わない
- 0件の `warning` は公開処理を止めない

## ASL定義

`infra/step-functions/kendo-keiko-scraper.asl.json` の次の値をデプロイ時にLambda ARNへ置換する。

- `${ListSourcesFunctionArn}`
- `${ScraperWorkerFunctionArn}`
- `${PublisherFunctionArn}`

## 今回の範囲外

- Step Functions、IAMロール、Schedulerの本番作成
- CloudWatch AlarmとSNS通知
- 公式側から消えたイベントの差分反映
- 手動イベント登録

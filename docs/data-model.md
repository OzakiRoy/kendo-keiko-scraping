# データモデル

## Organizations

団体情報。`data/organizations.json` で管理する。

主な項目:

- `organization_id`: システム内で使う固定ID
- `name`: 団体名
- `area`: 主な活動エリア
- `website_url`: 公式サイトURL
- `source_type`: `official_site` / `sns` / `manual`
- `scraper_type`: スクレイパー種別
- `scraper_enabled`: 自動取得対象かどうか
- `event_type`: `open_keiko` など

## Events

稽古会イベント情報。ローカルでは `data/events.json` に保存する。

主な項目:

- `event_id`: 安定生成されるイベントID
- `organization_id`: 団体ID
- `organization_name`: 団体名
- `event_date`: 稽古日
- `start_time`: 開始時刻
- `end_time`: 終了時刻
- `venue`: 会場名
- `area`: エリア
- `fee`: 参加費
- `application_required`: 申し込み必須かどうか
- `source_url`: 公式情報URL
- `source_type`: 情報取得元種別
- `last_scraped_at`: 最終取得日時
- `status`: `active` / `cancelled` / `unknown`

## 保存先

初期MVP:

```text
ローカル実行
  -> data/events.json
```

AWS移行後:

```text
EventBridge Scheduler
  -> Lambda または Fargate Scheduled Task
  -> DynamoDB
```

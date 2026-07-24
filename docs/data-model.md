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
- `application_required`: 申し込み必須かどうかを既存処理で推定した値
- `source_url`: 公式情報URL
- `source_type`: 情報取得元種別
- `last_scraped_at`: 最終取得日時
- `status`: `active` / `cancelled` / `unknown`
- `update_mode`: イベント情報の更新方式
- `participation_type`: イベントの参加条件
- `verified_at`: 内容を人が確認した日時。未確認は `null`

### update_mode

許可する値:

- `automatic`: スクレイパー等による自動取得
- `assisted`: 自動取得結果を人が補助して更新
- `manual`: 管理者が手動で登録・更新

自動スクレイパーが新規生成するイベントには `automatic` を明示する。
`ServiceEvent` 全体の暗黙のデフォルト値にはせず、将来の手動登録で誤分類しないようにする。

Issue #22以前に保存されたDynamoDB項目で属性が存在しない場合のみ、読み込み時の後方互換値として `automatic` を補う。

### participation_type

許可する値:

- `anyone`: 一般参加可能
- `contact_required`: 事前連絡が必要
- `registration_required`: 事前申し込みが必要
- `invitation_required`: 招待が必要
- `members_only`: 会員・所属者限定
- `unknown`: 公式情報から判断できない

Issue #22の最初のPRでは、既存の `application_required` から機械的に変換せず、新規自動取得イベントには `unknown` を設定する。誤判定を避け、参加条件の具体的な設定は情報源・イベントごとに追加する。

### verified_at

`verified_at` は ISO 8601形式かつタイムゾーン付きの日時、または `null` とする。

自動取得時刻をそのまま人による確認日時とは扱わないため、新規自動取得イベントは当面 `null` とする。DynamoDBでは未確認という状態を保持するため、`NULL` 属性として保存する。

Issue #22以前のDynamoDB項目に属性がない場合は、公開JSON生成時に `null` を補う。

## 公開JSONの後方互換性

Issue #22以前のイベントに新しい3属性がない場合、DynamoDB読み込み・公開JSON生成時に次を補う。

```json
{
  "update_mode": "automatic",
  "participation_type": "unknown",
  "verified_at": null
}
```

明示的に存在する不正な値は補正せず、バリデーションエラーにする。

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

## 手動イベント

管理者が確認して登録するイベントは `data/manual_events.json` でGit管理する。

追加項目:

- `review_due_at`: 次回確認期限。`YYYY-MM-DD`
- `status`: 手動イベントでは `active` / `cancelled` / `archived`

手動イベントでは次を必須とする。

- `update_mode: manual`
- 公式の `source_url`
- タイムゾーン付きの `verified_at`
- `review_due_at`

Publisher LambdaはDynamoDBの自動イベントと手動JSONを統合する。同じ団体・イベント種別・開催日・開始時刻・終了時刻のイベントは重複とみなし、手動イベントを優先する。手動イベントが `cancelled` または `archived` の場合は、対応する自動イベントも公開しない。

詳細は `docs/manual-events.md` を参照する。

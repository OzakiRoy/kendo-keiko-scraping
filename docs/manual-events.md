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

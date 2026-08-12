# 剣道稽古ナビ

## 概要

「参加できる稽古会を、日付・地域・参加条件から探す」を掲げ、社会人・一般参加者が参加しやすい剣道のオープン稽古会・合同稽古会を探せるWebサービス。

最初は公式サイトから取得できる団体のスクレイピングを中心に始める。将来的には、SNS中心の団体やスクレイピングしづらい団体について、団体側が自分で稽古予定を登録できるフォームを提供する。

## 目的

* 剣道の出稽古先・オープン稽古会を探しやすくする
* 参加人数を増やしたい団体と、稽古場所を探している剣士をつなぐ
* 公式情報への導線を作り、団体側の発信を支援する
* AWSサーバーレス、WAF、CSPM、スクレイピング基盤の実践題材にする

## 基本方針

### 1. 公式情報を尊重する

本サービスは、稽古会情報を集約して見つけやすくするためのサービスであり、最終的な正確性は各団体の公式情報を優先する。

各イベントには以下を必ず保持する。

* 公式URL
* 情報取得元
* 最終取得日時
* 最終更新日時
* 手動登録か自動取得か

画面上にも「参加前に必ず公式情報を確認してください」と表示する。

### 2. ユーザーアクセスごとにスクレイピングしない

スクレイピングはユーザーアクセス時に実行しない。

定期実行で取得した結果をDBに保存し、Web画面やAPIはDBの情報を参照する。

初期方針:

* 1日1〜2回程度の定期取得
* 取得失敗時は前回データを保持
* 最終取得日時を表示
* 取得元サイトへの負荷を抑える

### 3. スクレイピングと手動登録を併用する

団体の情報取得方式を以下に分ける。

* 公式サイトから取得できる団体
  → スクレイピングで自動取得

* SNS中心の団体
  → 最初は手動登録、将来的に団体側登録フォームを検討

* 更新頻度が低い団体
  → 管理者による手動登録

* 参加者を増やしたい団体
  → 団体側が自分で登録・更新できる仕組みを検討

## 初期対象団体

### 自動取得対象

* 社会人剣道サークルkent
* 剣究会
* 剣睦会

### 今後検討

* ケンプラ
* 残心稽古会
* 三無の会
* 純剣会
* HAGAKUREY
* その他、関東のオープン稽古会

SNS依存の団体は、スクレイピングで無理に取得するのではなく、登録フォームや手動登録による運用を検討する。

## AWS構成方針

初期構成はサーバーレスを基本とする。

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

定期取得処理:

```text
EventBridge Scheduler
  ↓
Lambda scrape_job
  ↓
DynamoDB
```

将来的にスクレイピング対象が増えたり、処理が重くなった場合:

```text
EventBridge Scheduler
  ↓
ECS Fargate Scheduled Task
  ↓
DynamoDB
```

## 採用予定AWSサービス

* Route 53
* CloudFront
* AWS WAF
* S3
* API Gateway
* Lambda
* DynamoDB
* EventBridge Scheduler
* CloudWatch Logs
* Security Hub CSPM
* AWS Config
* GuardDuty
* IAM Access Analyzer
* Prowler

## Fargateの位置づけ

初期段階ではWeb API本体をFargateにしない。

APIは API Gateway + Lambda を基本とする。

Fargateは、以下の条件が出てきた場合にスクレイピングジョブ用として導入する。

* 対象団体が増えた
* Lambdaの実行時間や依存ライブラリ制約が厳しくなった
* Playwrightなどのheadless browserが必要になった
* Dockerでスクレイピング環境を固定したくなった

## WAF運用方針

CloudFrontにAWS WAFを適用する。

初期ルール候補:

* AWS Managed Rules Common Rule Set
* Known Bad Inputs
* SQLi Rule Set
* Rate-based rule
* Botらしい連続アクセス制限

最初はCountモードで観察し、誤検知を確認してからBlockに切り替える。

## CSPM / セキュリティ運用方針

このサービス基盤自体を、AWSセキュリティ運用・CSPM・WAF運用の実験台にする。

確認対象:

* Security Hub CSPM
* AWS Config
* GuardDuty
* IAM Access Analyzer
* Prowler
* WAFログ
* CloudTrail
* CloudWatch Logs

将来的には、Prowler + 生成AIによるAWS健康診断サービスの検証対象としても使う。

## データ設計

### Organizations

団体情報。

```text
organization_id
name
area
website_url
source_type: official_site / sns / manual
scraper_enabled
last_checked_at
created_at
updated_at
```

### Events

稽古会イベント情報。

```text
event_id
organization_id
event_date
start_time
end_time
venue
address
area
event_type
fee
application_required
source_url
last_scraped_at
status: active / cancelled / unknown
created_at
updated_at
```

### Sources

取得元情報。

```text
source_id
organization_id
source_url
scraper_type
last_success_at
last_error
created_at
updated_at
```

## 開発状況とロードマップ

現在は、スクレイピング基盤を作る段階から、自動取得と手動登録を組み合わせて掲載情報を増やし、利用者が稽古先を探しやすくする段階へ移行している。

本番環境では、次の仕組みが稼働している。

* S3 + CloudFrontによる静的サイト配信
* EventBridge Scheduler + Step Functionsによる定期取得
* 6情報源からの自動取得
* `data/manual_events.json` と管理者CLIによる手動登録
* Publisherだけを更新する手動イベントの1コマンド公開
* DynamoDBの自動イベントと手動イベントの公開時統合
* 参加条件・取得方式・確認日のイベント単位管理
* CloudWatch Alarm + SNSによる失敗通知

直近は次の順序を基本とする。

1. Instagramを通じて利用者・掲載団体との接点を作る
2. 掲載件数の増加に耐えるトップページと検索UXへ改善する
3. 地域団体・剣道連盟の掲載情報を継続的に増やす
4. Googleカレンダー追加や共有など、実利用に直結する便利機能を追加する
5. 実際の需要と情報量を見ながら、掲載依頼・イベント詳細・地域別ページを段階的に検討する

日付・地域・参加条件・団体・キーワードによる絞り込み、ブランド整備、Publisherだけを更新する手動イベントの1コマンド公開は完了済み。現在はInstagram運用と、掲載情報が増えても人間が使いやすいUIへの改善を優先する。イベント差分と掲載状態の安全管理は重要だが、運用負荷が顕在化した段階で優先度を引き上げる。

詳細な優先順位、運用原則、完了済み項目は [`docs/roadmap.md`](docs/roadmap.md) を参照する。

## 開発メモ

このサービスは、単なるスクレイピングツールではなく、社会人剣道のオープン稽古会情報を集約するサービスとして育てる。

技術的には、AWSサーバーレス、WAF、CSPM、スクレイピング、DynamoDB設計、運用監視の実践題材にする。

事業的には、剣道団体と参加者をつなぐ小さなサービスとして始め、将来的に団体登録・地域展開・AWS運用事例として活用する。


## 基本SEOの静的生成

開催予定はブラウザのJavaScript表示に加え、定期Lambda実行時に `index.html` へ静的生成する。`events.json`、`index.html`、`sitemap.xml` を同じデータ更新サイクルでS3へ発行し、HTMLと表示データの鮮度を揃える。

実装・デプロイ手順は `docs/basic-seo-setup.md` を参照する。

## 手動イベント管理

自動取得しない団体のイベントは `data/manual_events.json` で管理する。

```bash
python manage_manual_events.py --help
python manage_manual_events.py list
python manage_manual_events.py list-review-due
```

登録・一括登録・更新・中止・アーカイブ・再確認と `--dry-run` に対応している。新規団体の追加手順は [`docs/manual-events.md`](docs/manual-events.md)、Publisherだけを更新する1コマンド公開は [`docs/manual-events-runbook.md`](docs/manual-events-runbook.md) にまとめている。

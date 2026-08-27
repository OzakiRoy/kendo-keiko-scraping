# Codexによる稽古会登録・公開runbook

## 目的

Codexが公式情報を根拠に、掲載団体と手動イベントを安全に登録し、レビュー後に本番公開するための標準手順を定める。

CLIの項目とデータ仕様は [`../manual-events.md`](../manual-events.md)、Publisherの実装上の検査と公開対象は [`../manual-events-runbook.md`](../manual-events-runbook.md) を正とする。この文書は、CodexがGitHub、worktree、PR、MFAを含む一連の作業を進める際の境界と停止条件を補う。

## 絶対条件

- 公開GitHubの最新 `origin/main` を最優先の正とする。
- 1団体またはレビュー可能な1変更を `1 Issue / 1 PR` で扱う。
- 公式情報にない内容を推測、補完しない。
- 元のdirty worktreeを、許可なく編集、restore、stash、rebase、checkout、削除しない。
- CLIや生成処理が対象外レコードや対象外ファイルを変更した場合は停止する。
- PRのmergeと本番publishは、それぞれユーザーの明示的な指示があるまで行わない。
- feature branchから本番publishしない。
- 自動スクレイパーやStep Functions全体を、手動イベント公開のために実行しない。
- 想定外の結果を手編集や別コマンドで回避せず、停止して報告する。

## フェーズ1: 調査

変更前に読み取り専用で次を確認する。

1. 現在のbranchと `git status --short --branch`
2. `git fetch origin` 後の `origin/main` と公開GitHubのmain SHA
3. open Issues、open PR、最近の関連PRと変更ファイル
4. `README.md`、`docs/roadmap.md`、本runbook、関連文書
5. `data/organizations.json` と `data/manual_events.json`
6. `manage_manual_events.py` と `kendo_keiko/manual_events.py`
7. `scripts/generate_organization_section.py`
8. `tests/test_manual_event_data.py` と関連テスト
9. `scripts/publish_manual_events.sh`
10. 必要な場合は本番 `events.json` と公式情報源

公式情報から確認できる値と不明な値を分ける。住所、アクセス、料金などが不明なら、モデルが許容する `null` を使い、外部サイトや一般知識から補完しない。曜日などCLIが日付から機械的に生成する値は、生成結果を確認する。

## フェーズ2: Issueと安全なworktree

先行するIssueやPRがなければ、調査結果、公式情報源、登録方針、完了条件を記載したIssueを1件作る。

現在のworktreeがdirtyな場合は、そのworktreeを保全し、最新mainから独立worktreeを作る。

```bash
git fetch origin
git rev-parse origin/main
git ls-remote origin refs/heads/main

git worktree add \
  -b feature/issue-NUMBER-short-description \
  /tmp/kendo-keiko-issue-NUMBER \
  origin/main
```

新worktreeで次を確認する。

```bash
git branch --show-current
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

HEADと `origin/main` が一致し、tracked filesがcleanでなければ変更を始めない。

既存のdirty worktreeに同じ作業の未コミットデータがある場合も、JSONファイル全体や古いdiffを新worktreeへ適用しない。最新main上で正規のCLIを再実行し、後から対象オブジェクトだけを意味的に比較する。

## フェーズ3: 団体登録

新規団体の場合だけ `data/organizations.json` を既存の並びと形式に合わせて更新する。

最低限、次を公式情報と既存モデルから確定する。

- `organization_id`
- `name`
- `area`
- `website_url`
- `source_type`
- `scraper_type`
- `scraper_enabled`
- `event_type`
- `public_description`
- デフォルトの参加条件と申込要否

既存団体なら、イベント追加のためだけに団体マスタや `public/index.html` を変更しない。

## フェーズ4: イベント登録

1件の追加は `manage_manual_events.py add` を使う。同一内容の複数日追加だけ `add-batch` を使う。

タイムゾーン付き `verified_at` と `review_due_at` を指定し、最初に `--dry-run` を実行する。

```bash
PATH="/home/ozaki/project/kendo-keiko-scraping/.venv/bin:$PATH" \
python manage_manual_events.py add \
  --organization-id ORGANIZATION_ID \
  --date YYYY-MM-DD \
  --title "公式情報に基づくタイトル" \
  --start-time HH:MM \
  --end-time HH:MM \
  --venue "公式情報に基づく会場" \
  --source-url "OFFICIAL_URL" \
  --participation-type TYPE \
  --application-required APPLICATION_REQUIRED \
  --verified-at "YYYY-MM-DDTHH:MM:SS+09:00" \
  --review-due-at YYYY-MM-DD \
  --dry-run
```

dry-runでは、件数、event ID、日付、曜日、時刻、会場、null項目、参加条件、公式URL、確認期限を確認する。正常なら同じ引数から `--dry-run` だけを外して登録する。

`APPLICATION_REQUIRED` にはCLIが受け付ける `yes`、`no`、`unknown` のいずれかを、公式情報と既存モデルに基づいて指定する。

登録後、必ず次を確認する。

```bash
git diff --numstat -- data/manual_events.json
git diff -- data/manual_events.json
```

期待する差分は対象イベントの追加または更新だけである。既存イベントの移動や変更があれば停止する。生JSONの順序は `tests/test_manual_event_data.py` のcanonical-orderテストでも検証する。

古いdirty worktreeの対象イベントと比較する場合は、`verified_at` と `last_scraped_at` の再確認時刻だけを許容し、次を確認する。

- event IDが同一である
- その他の意味的内容が同一である
- 最新mainに元からあるイベントの順序と内容が不変である

event IDが変わった場合は原因を調査し、先へ進まない。

## フェーズ5: 生成とテスト

新規団体の場合だけ掲載団体セクションを生成する。

```bash
PATH="/home/ozaki/project/kendo-keiko-scraping/.venv/bin:$PATH" \
python scripts/generate_organization_section.py

git diff -- public/index.html
```

対象団体の追加以外のHTML差分があれば停止する。

データ内容を固定する関連テストを追加し、少なくとも次を検証する。

- 団体との関連付け
- event IDとイベント件数
- 日付、時刻、会場、タイトル
- 参加条件と申込要否
- 不明項目が `null` であること
- 公式URLと取得方式

PR前に次をすべて実行する。

```bash
git diff --check

PATH="/home/ozaki/project/kendo-keiko-scraping/.venv/bin:$PATH" \
python -m unittest -v RELATED_TEST_MODULES

PATH="/home/ozaki/project/kendo-keiko-scraping/.venv/bin:$PATH" \
python -m unittest discover -s tests -v
```

イベントまたは団体を変更した場合は、JST当日を明示したpublish dry-runも実行する。`FROM_DATE` は環境から除外する。

```bash
env -u FROM_DATE \
  PATH="/home/ozaki/project/kendo-keiko-scraping/.venv/bin:$PATH" \
  scripts/publish_manual_events.sh \
    --organization-id ORGANIZATION_ID \
    --expected-count EXPECTED_COUNT \
    --from-date "$(TZ=Asia/Tokyo date +%F)" \
    --dry-run
```

`EXPECTED_COUNT` は追加件数ではなく、基準日以降の対象団体のactiveな手動イベント総数である。

## フェーズ6: commit、push、PR

最終diffで変更ファイルと変更内容を目視確認し、無関係なdiffがないことを確認する。対象ファイルだけを明示的にstageする。

```bash
git status --short --branch
git diff --stat
git diff --name-status
git diff --check

git add PATHS_FOR_THIS_ISSUE
git diff --cached --check
git commit -m "TYPE: summary (#NUMBER)"
git push -u origin HEAD
```

PR本文には次を記載する。

- `Closes #NUMBER`
- 公式情報源
- 登録した団体とイベント
- 最新mainの基準SHA
- CLI dry-runとdiff確認結果
- 関連テスト、全テスト、`git diff --check` の結果
- publish dry-runの基準日、期待件数、結果
- mergeと本番deployを行っていないこと

PR作成後は停止する。ユーザーの明示的な指示なしにmergeしない。

## フェーズ7: merge後の本番publish

ユーザーから本番publishを明示的に指示された場合だけ実施する。元のdirty worktreeやfeature worktreeは使わず、最新main専用のclean worktreeを使う。

```bash
git fetch origin
git ls-remote origin refs/heads/main
gh pr view PR_NUMBER --json state,mergedAt,mergeCommit

# main worktreeの有無とパスを確認する
git worktree list

# main worktreeが存在しない場合だけ新規作成する
git worktree add /tmp/kendo-keiko-main-publish main
cd /tmp/kendo-keiko-main-publish
git merge --ff-only origin/main

git branch --show-current
git status --short --branch
git rev-parse HEAD
git rev-parse '@{upstream}'
```

最初に `git worktree list` でmain worktreeの有無とパスを確認する。既存のmain worktreeがあれば、そのworktreeが最新、upstream一致、tracked files cleanであることを確認して再利用する。存在しない場合だけ新規作成する。次の条件が1つでも満たされなければpublishしない。

- 対象PRがmerge済み
- branchが `main`
- HEADと最新の公開 `origin/main` が一致
- upstream一致
- tracked files clean
- 対象団体とイベントが最新mainに存在
- `public/index.html` が生成済み

本番AWS操作ではプロファイルを明示する。正しい環境変数名は `AWS_PROFILE` であり、このリポジトリの本番publishでは `admin` を使用する。

`FROM_DATE` をexportせず、同一コマンドの環境から除外してJST当日を使う。

```bash
env -u FROM_DATE \
  AWS_PROFILE=admin \
  PATH="/home/ozaki/project/kendo-keiko-scraping/.venv/bin:$PATH" \
  scripts/publish_manual_events.sh \
    --organization-id ORGANIZATION_ID \
    --expected-count EXPECTED_COUNT \
    --from-date "$(TZ=Asia/Tokyo date +%F)"
```

このコマンドは `KendoKeikoPublisher` だけを更新し、`publish_only` で直接実行する。MFAを求められた場合は、CodexへMFAコードを渡さず、ユーザー自身が対話TTYへ直接入力する。CodexはMFAコードを読み取り、転記、保存しない。MFAコードをログ、commit、Issue、PR、最終報告へ記載しない。

## フェーズ8: 本番確認

publishスクリプトの完了出力で次を確認する。

- AWSアカウントと `assumed-role/Admin`
- Lambdaのローカル・リモートコードhash一致
- Lambda invokeのStatusCodeが200
- `mode` が `publish_only`
- `s3_published`、`index_published`、`sitemap_published` がtrue
- S3原本の対象団体イベント数が期待値と一致
- 必須メタデータの欠損がない

次に、公開サイトの `events.json` と `index.html` を読み取り確認する。

- 対象event IDが1件だけ存在する
- タイトル、日時、会場、参加条件、公式URLが登録内容と一致する
- 掲載団体セクションが表示される

CloudFrontのキャッシュで直前のHTMLが返る場合があるため、最初の正はpublishスクリプトが検証したS3原本とする。公開サイト確認には必要に応じて一意なquery stringを付ける。

本番確認後も、元のdirty worktreeを変更または削除しない。結果をユーザーへ報告して停止する。

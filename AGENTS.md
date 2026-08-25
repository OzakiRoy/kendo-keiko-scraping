# AGENTS.md

このファイルはリポジトリ全体に適用する。Codexは着手前に必ず読み、ここに記載した確認順序、変更単位、安全条件に従う。

## 情報源の優先順位

判断が食い違う場合は、次の順序を優先する。

1. 公開GitHub上の最新 `origin/main`
2. GitHub Issues、Pull Requests、`docs/roadmap.md`
3. 最新 `main` のローカル実ファイル（README、設計・運用ドキュメント、実装、データを含む）
4. 既存テスト
5. 現在の本番公開データ
6. 過去の会話や補助的なメモ

- 過去の会話、記憶、一般論、推測だけを根拠に変更しない。
- 情報が不足している、矛盾している、または確認できない場合は推測せず、作業を停止してユーザーへ報告する。
- roadmapやドキュメント内のIssue番号とGitHubの現状が異なる場合は、GitHubの現状を優先し、不一致を報告する。

## 作業開始前の必須確認

変更を始める前に、読み取り専用で次を確認する。

1. `git branch --show-current` と `git status --short --branch`
2. 公開GitHubの `origin/main` の最新SHA
3. open Issuesと最近のPR（関連Issue・PRの本文、変更ファイル、検証結果を含む）
4. `README.md` と `docs/roadmap.md`
5. 作業に関係する設計・運用ドキュメント
6. 変更対象の実ファイルとデータ構造
7. 関連テストと全テストの実行方法
8. `scripts/publish_manual_events.sh` と関連する公開処理
9. 必要な場合は本番 `events.json` などの公開データ

- 公開GitHubの最新 `origin/main` とローカル `main` が一致していることを確認してからbranchを作る。
- 先行・競合するIssueまたはPRがある場合は、新しい作業を開始せずユーザーへ報告する。
- 既存の未コミット変更を上書き、削除、混入しない。

## Issue・branch・PRの単位

- 原則として `1 Issue / 1 PR` とする。
- 1つのIssueでは、レビュー可能な小さい変更単位だけを扱う。
- Issueにない関連修正やリファクタリングを勝手に追加しない。
- branchは最新 `main` から作り、Issue番号をbranch名とcommit、PRから追跡できるようにする。
- 無関係なdiff、生成物、ローカル環境の変更をcommitまたはPRへ含めない。
- PR本文にはIssueへの参照、変更内容、根拠となる情報源、確認結果、実行したテスト、publish dry-run結果を記載する。
- PRのmergeは、ユーザーから明示的な指示があるまで絶対に行わない。

## イベント・団体情報の安全ルール

- 変更前に `data/manual_events.json`、`data/organizations.json`、データモデル、CLI実装、関連テストを実物から確認する。
- 公式サイト、公式SNS、または主催者から直接提供された情報を根拠にする。
- 公式情報にない住所、アクセス、時刻、料金、参加条件、申込要否などを推測して補完しない。値が確認できなければ、既存モデルで許される `null` または `unknown` を使えるか確認し、不明なら停止する。
- イベントタイトルは公式の表現を優先する。
- 団体名の旧字体・異体字は公式表記を優先する。
- 主催者から直接修正された情報は、古い投稿画像や過去の掲載内容より優先する。根拠となるIssueや記録をPRへ示す。
- 既存団体の安定した `organization_id` は、名称修正だけを理由に変更しない。
- 手動イベントには公式 `source_url`、タイムゾーン付き `verified_at`、`review_due_at`、適切な `participation_type` と `application_required` を設定する。
- 1件追加では原則 `manage_manual_events.py add`、同一内容の複数日追加では `add-batch` を使用し、先に `--dry-run` で出力を確認する。
- CLI実行前後で対象JSONのdiffを確認する。`manage_manual_events.py` などが既存データを不要に並び替えたり、対象外レコードを書き換えたりした場合は、そのdiffをPRへ含めず、作業を停止して報告する。自分の判断で手編集して回避しない。
- 対象団体が既に `data/organizations.json` に存在する場合、必要のない団体マスタ変更や `public/index.html` 再生成を含めない。
- 新規団体を追加する場合だけ、現在の手順に従って団体マスタと掲載団体セクションを更新する。

## 検証

PR作成前に、変更内容に応じて次をすべて行う。

1. `git diff --check`
2. diffの目視確認と `git status --short`
3. 関連テスト
4. 全テスト: `python -m unittest discover -s tests -v`
5. publish dry-run: `scripts/publish_manual_events.sh --dry-run`（イベントまたは団体を変更した場合は `--organization-id` と `--expected-count` も指定する）

- リポジトリの仮想環境を使う場合は、コマンド実行前に `.venv` を有効化し、スクリプトが要求する `python` をPATHへ入れる。
- `--expected-count` は追加件数ではなく、JSTの基準日以降に公開対象となる、その団体の `active` な手動イベント総数とする。
- テストやdry-runが失敗した場合、期待値を安易に変更したり、検証を省略したりしない。原因を特定できなければ停止して報告する。
- 想定外のファイル変更、件数、並び順、生成結果、公開結果が出た場合は、自分の判断で回避せず停止して報告する。

## `FROM_DATE` とpublishの安全ルール

- `FROM_DATE` はexportしない。
- 基準日を固定する必要がある場合は、環境変数ではなく `--from-date YYYY-MM-DD` をそのコマンドに明示する。
- 本番publish前には必ず `unset FROM_DATE` を実行し、JST当日が使われる状態にする。
- dry-runと本番publishを明確に区別する。検証中は必ず `--dry-run` を付ける。
- 本番publishはfeature branchから絶対に実行しない。
- 本番publishは、PRがmerge済みで、最新 `main`、upstream一致、tracked filesがcleanであることを確認してから行う。
- 本番publishおよびその他の本番deployは、ユーザーからその操作について明示的な指示があるまで絶対に行わない。
- 手動イベント公開では現在のrunbookに従い、許可なく自動スクレイパーやStep Functions全体を実行しない。

## 停止条件

次のいずれかに該当したら、追加の変更、commit、push、PR作成、merge、deployへ進まず、現状と確認結果をユーザーへ報告する。

- 最新 `origin/main` を確認できない、またはローカルと安全に同期できない
- 作業範囲や公式情報が不明確
- Issue、PR、roadmap、実装、テスト、本番データが重要な点で矛盾する
- 既存のユーザー変更や無関係なdiffがある
- CLIや生成処理が対象外データを変更した
- 関連テスト、全テスト、`git diff --check`、publish dry-runのいずれかが失敗した
- 実行結果が事前の想定と異なる
- mergeまたは本番deployについてユーザーの明示的な指示がない

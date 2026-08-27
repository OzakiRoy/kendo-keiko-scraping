# kendo-keiko.com 日常運用

kendo-keiko.com で日常的に実施する運用の入口をまとめる。

詳細な登録・公開手順は各Runbookを正とする。

---

## 0. 共通: 作業開始

リポジトリへ移動する。

```bash
cd ~/project/kendo-keiko-scraping
```

Python仮想環境を有効化する。

```bash
source .venv/bin/activate
```

通常作業の開始前は、最新mainを確認する。

```bash
git switch main
git fetch origin --prune
git pull --ff-only

git status --short --branch
```

期待状態:

```text
## main...origin/main
```

作業終了時:

```bash
deactivate
```

---

## 1. 新しい団体を追加する

新規団体の追加はCodexへ依頼する。

Codexには必ず以下を参照させる。

- `AGENTS.md`
- `docs/runbooks/codex-keiko-registration.md`

新規団体の場合は、最初に調査・登録案を提示させて一度停止する。

### Codexへの依頼例

```text
kendo-keiko.com に新しい団体と稽古会情報を追加してください。

団体公式URL:
<URL>

稽古会公式情報URL:
<URL>

添付画像がある場合は、それも公式情報源として使用してください。

AGENTS.md と
docs/runbooks/codex-keiko-registration.md
に従ってください。

新規団体なので、まず読み取り専用で以下を確認してください。

- 最新GitHub main
- open Issue / PR
- 既存団体
- 既存イベント
- 公式情報
- organization_id候補
- participation_type
- application_required
- 変更予定ファイル

organization と event の登録案、
判断事項、不明点、実装計画を提示して一度停止してください。

この段階では、
Issue作成、branch作成、ファイル変更、commit、push、PR作成、
merge、deployは行わないでください。
```

内容を確認して問題なければ、続けて以下を依頼する。

```text
調査内容で進めてください。

AGENTS.md と
docs/runbooks/codex-keiko-registration.md
に従い、

Issue作成
→ branch/worktree
→ 実装
→ dry-run
→ diff確認
→ tests
→ commit
→ push
→ PR作成

まで進めてください。

PR作成後は停止してください。
merge / deployは禁止です。
```

PRレビュー後のmerge・本番publishも
`docs/runbooks/codex-keiko-registration.md`
に従う。

---

## 2. 既存団体へ稽古会を追加する

既存団体への稽古会追加もCodexへ依頼する。

Codexには必ず以下を参照させる。

- `AGENTS.md`
- `docs/runbooks/codex-keiko-registration.md`

既存団体で公式情報と既存設定が明確なら、
原則としてPR作成まで進めてよい。

### Codexへの依頼例

```text
kendo-keiko.com に以下の稽古会情報を追加してください。

団体:
<団体名>

公式情報URL:
<URL>

添付画像がある場合は、それも公式情報源として使用してください。

AGENTS.md と
docs/runbooks/codex-keiko-registration.md
に従ってください。

既存団体なので、以下を確認してください。

- 最新GitHub main
- open Issue / PR
- organization_id
- 既存の参加条件
- application_required
- 料金
- タイトル命名規則
- 過去の主催者からの直接修正情報
- 既存イベントとの重複

問題がなければ、

Issue作成
→ branch/worktree
→ CLI dry-run
→ イベント追加
→ diff確認
→ tests
→ publish dry-run
→ commit
→ push
→ PR作成

まで進めてください。

対象外イベントの変更・移動・並び替えなど、
想定外のdiffが発生した場合は停止してください。

PR作成後は停止してください。
merge / deployは禁止です。
```

PRレビュー後のmerge・本番publishも
`docs/runbooks/codex-keiko-registration.md`
に従う。

---

## 3. Instagram週末Story画像を生成する

週末Story画像生成は通常運用であり、
コード変更を伴わないためCodexは不要。

通常は以下も不要。

- Issue
- branch
- commit
- PR
- deploy

最新mainの既存CLIを実行する。

### 3.1 準備

```bash
cd ~/project/kendo-keiko-scraping

git switch main
git fetch origin --prune
git pull --ff-only

source .venv/bin/activate

git status --short --branch
```

Story用依存が未導入の場合のみ実行する。

```bash
pip install -r requirements-story.txt
```

### 3.2 Story画像生成

対象週末の「土曜日」を `--date` に指定する。

```bash
python scripts/generate_weekend_story.py \
  --date YYYY-MM-DD \
  --output output/weekend-story.png
```

例:

```bash
python scripts/generate_weekend_story.py \
  --date 2026-08-29 \
  --output output/weekend-story.png
```

通常の入力データは、本番公開済みの以下を使用する。

```text
https://kendo-keiko.com/events.json
```

`data/manual_events.json` を直接入力の正にしない。

複数ページになる場合は、例えば以下のように生成される。

```text
output/weekend-story-01.png
output/weekend-story-02.png
output/weekend-story-03.png
```

### 3.3 Windowsで生成画像を確認

WSLからExplorerを開く。

```bash
explorer.exe "$(wslpath -w "$PWD/output")"
```

Instagramへ投稿する前に、人間が必ず生成画像を目視確認する。

最低限以下を確認する。

- 1080 x 1920
- 対象の土日が正しい
- イベント件数が妥当
- 日付・時刻
- 団体名
- イベント名
- 会場
- 参加条件
- 参加費
- ページ順
- 文字切れ
- 不自然な改行
- 剣道稽古ナビのブランド表示
- 無許諾の団体ロゴ・生成アイコンがない
- 公式情報確認の注意書き

正式表記にも注意する。

例:

- `西劔会`
- `絆剱会`

CLIが `[NO_EVENTS]` を出力して終了コード3を返した場合は、
Storyを投稿しない。

### 3.4 問題が見つかった場合

以下のようなコード修正が必要な問題が見つかった場合は、
日常運用中にその場でコードを修正しない。

例:

- レイアウト崩れ
- 文字切れ
- 未対応文字
- CLIエラー
- `events.json` 仕様変更
- 参加条件表示の不具合

その場合だけ通常の開発フローへ切り替える。

```text
Issue
→ branch
→ 修正
→ tests
→ PR
```

---

## 運用一覧

| 作業 | 実施方法 |
| --- | --- |
| 新規団体追加 | Codex + `codex-keiko-registration.md` |
| 既存団体への稽古会追加 | Codex + `codex-keiko-registration.md` |
| Instagram週末Story画像生成 | 人間がPython CLI実行 |
| Story生成機能の修正 | Issue / branch / PR |

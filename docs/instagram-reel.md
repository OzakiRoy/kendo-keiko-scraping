# 金〜日 Instagram Reel 自動生成・投稿

## 目的と安全な初期状態

`scripts/generate_instagram_reel.py` は、本番の
`https://kendo-keiko.com/events.json` を検証し、水曜日（木曜日は遅延実行）に
直後の金・土・日を抽出して、既存Storyと同じ1080×1920デザインのReel素材を
生成する。既定は `--dry-run` で、認証・S3アップロード・Instagram投稿を行わない。
タスク登録と有効化もこの実装では行わない。

生成先は `output/instagram-reel/YYYY-MM-DD/`（`reel.mp4`、`cover.png`、
`caption.txt`、`manifest.json`）で、gitignore対象である。状態と履歴は
`~/.local/share/kendo-keiko/instagram-reel/`（または
`INSTAGRAM_REEL_STATE_DIR`）に保存する。

## 抽出と表示

- payloadの `schema_version=public-events-0.3` と `timezone=Asia/Tokyo` を必須検証する。
- 通常はJST水曜に金曜を決め、木曜は同じ週の遅延実行とする。金曜以降は投稿せず
  `skipped_late` を状態へ記録する。`--target-friday YYYY-MM-DD` は明示的な手動対象指定。
- `status=active` のみを対象にし、`cancelled` / `archived` はmanifestへ除外理由を記録する。
- `open_keiko` と `federation_keiko` は「稽古会」、`adult_renseikai` は
  「大人向け錬成会・練習試合」と表示する。`unknown`や必須項目不足は投稿対象から除外する。
- 地域は `--area` を複数指定でき、省略時は掲載地域全体を対象にする。
- 0件は投稿せず終了コード3。取得失敗、未知schema、不正日付はエラーとして記録する。
- 文字列、料金、参加条件、申込要否はevents.jsonの値を保持し、生成AIで変更しない。

## Reel仕様

- 1080×1920、H.264、yuv420p、無音AAC、30fps、ページ6秒（3〜900秒の範囲）。
- 音楽・BGMは添付しない。
- ページ数はイベント数と実測レイアウトから決め、イベントを恣意的に削らない。
- 表紙は先頭ページ。captionとmanifestには対象金曜日、対象event ID、除外理由、入力SHA-256、
  動画検査結果を保存する。

ローカル依存のセットアップ:

```bash
cd /home/ozaki/project/kendo-keiko-scraping
.venv/bin/python -m venv .venv-reel
.venv-reel/bin/python -m pip install -r requirements-story.txt
```

本番events.jsonを使うdry-run（実行日は水曜でなくても明示指定できる）:

```bash
scripts/run_instagram_reel.sh \
  --target-friday 2026-10-09 \
  --dry-run
```

fixtureでの検証:

```bash
scripts/run_instagram_reel.sh \
  --target-friday 2026-10-09 \
  --events-file tests/fixtures/weekend_reel_events.json \
  --output-dir /tmp/kendo-reel-preview \
  --state-dir /tmp/kendo-reel-state \
  --dry-run
```

## Meta公式APIと認証

参照する公式仕様:

- [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/)
- [Content Publishing](https://developers.facebook.com/docs/instagram-api/guides/content-publishing)
- [IG User media](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media)
- [IG User media_publish](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media_publish)

実アカウントの接続状態と認証情報は未確認のため、今回のPRではモードを自動推測しない。
`INSTAGRAM_AUTH_MODE` を明示的に `instagram_login` または `facebook_login` にする。

| モード | API host | 主な前提 |
| --- | --- | --- |
| `instagram_login` | `graph.instagram.com` | Business Login for Instagram、Businessアカウント、`instagram_business_basic` と `instagram_business_content_publish` の設定 |
| `facebook_login` | `graph.facebook.com` | Facebook Pageに接続したInstagram Businessアカウント、Page access token、Facebook Login側のInstagram publishing権限 |

API versionは `INSTAGRAM_GRAPH_API_VERSION`（既定 `v25.0`）で固定する。Meta管理画面で
採用バージョンとpermissionを確認してから変更する。tokenは環境変数へ直接書く場合もgit管理外の
600権限ファイルから読み込み、ログ・PR・manifestへ出さない。

投稿は次の順で行う。

1. destination IDとusernameを読み取り専用APIで照合し、Business/Creator以外なら停止。
2. 専用S3キー（`INSTAGRAM_REEL_VIDEO_PREFIX`）へMP4を置き、HEADとHTTP RangeでMetaから到達可能か確認。
3. `/{ig-user-id}/media` に `media_type=REELS` と `video_url` を指定してcontainer作成。
4. `status_code` がFINISHEDになるまで期限付きpoll。ERRORは失敗、timeoutは結果不明として停止。
5. `/{ig-user-id}/media_publish` で公開し、media IDを取得。
6. mediaのpermalinkを取得し、状態JSONと履歴へ保存。

公開API呼び出しの応答が失われた場合、二重投稿防止のため `unknown` と記録して自動再投稿しない。
同じ投稿先ID・対象金曜日の `published`、`unknown`、処理中状態は再実行を拒否する。

## WSLとWindows Task Scheduler

WSL側は `scripts/run_instagram_reel.sh` を絶対パスの専用venvで起動する。
対話シェルのPATHやvenv有効化には依存しない。WSLユーザー、ディストリビューション、
リポジトリ絶対パスを実機で確認する。

登録用PowerShellは初期状態で**表示だけのdry-run**であり、Windowsタスクを作成しない。
Windowsのタイムゾーンが `Tokyo Standard Time` であることを確認してから、値を見直す。
水曜18:00（変更可能）に登録し、`-Apply` を付けた場合でも `-Enable` がない限り無効状態で作成する。
`-Publish` を付けない登録では、タスクのActionも `--dry-run` になる。認証・動画到達性・手動投稿を確認するまで、`-Enable` と `-Publish` は指定しない。

```powershell
.\scripts\register_instagram_reel_task.ps1 `
  -TaskName KendoKeikoInstagramReel `
  -WslDistro Ubuntu `
  -LinuxUser ozaki `
  -RepoPath /home/ozaki/project/kendo-keiko-scraping `
  -Time 18:00
```

登録前チェック:

```powershell
$env:USERNAME
[System.TimeZoneInfo]::Local.Id
wsl.exe -l -v
wsl.exe -d Ubuntu -u ozaki -- /home/ozaki/project/kendo-keiko-scraping/scripts/run_instagram_reel.sh --target-friday 2026-10-09 --dry-run
```

投稿を有効化するのは、Meta destinationの読み取り確認、S3動画URLの外部到達確認、
fixtureと本番events.jsonの動画確認、手動の一度の投稿確認が済んだ後だけにする。
PC起動・ネットワーク・ログオン中設定が必要で、停止中に逃した週は自動で別週へずらさず、
木曜までの遅延実行または明示的な `--target-friday` で扱う。

## 状態と失敗処理

状態は `dry_run`、`prepared`、`destination_verified`、`container_created`、
`container_processing`、`published`、`skipped_*`、`failed`、`unknown` を区別する。
生成一時ファイルと状態ディレクトリは分離し、fcntlロックで同時起動を防ぐ。
通信retryはcontainer作成・照会など安全な処理に最大2回、公開リクエストには行わない。
Slackやメール通知は実装しない。

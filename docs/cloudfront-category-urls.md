# CloudFrontカテゴリURL適用runbook

## 対象と未確認事項

非公開S3のREST endpoint＋OACを維持する。DefaultRootObjectだけではサブディレクトリのindex.htmlは返らないため、`infra/cloudfront/category-urls.js` をcloudfront-js-2.0のviewer-request Functionとして用意する。

- GET/HEAD `/keiko` → 301 `/keiko/`（クエリ保持）
- GET/HEAD `/renseikai` → 301 `/renseikai/`（クエリ保持）
- `/keiko/`, `/renseikai/` → 同ディレクトリのindex.htmlへ内部書き換え
- GET/HEAD `/area/kanto`, `/area/tokyo` → 301で末尾スラッシュを追加（クエリ保持）
- `/area/kanto/`, `/area/tokyo/` → 各地域のindex.htmlへ内部書き換え
- それ以外のパス・メソッドは変更しない。`/keiko/index.html` は直接配信しcanonicalで `/keiko/` を指定する。

クエリはCloudFront eventの既存エンコードを保ち、multiValueの重複値を欠落・二重エンコードさせない。空値は `name=` として保持する。パラメータの異なる名前同士の元の並び・`flag` と `flag=` の表記差はevent構造から復元できないため保証しない。リダイレクトはブラウザへの固定化を避けるため `Cache-Control: no-store`。

**本番のDistribution、Function／Lambda@Edge関連付け、CachePolicy／OriginRequestPolicy、エラーキャッシュ、IAM・S3権限は未確認。このPRは本番適用を含まない。**

## 適用前確認（本番操作の明示許可後）

1. 対象Distributionの全設定とETag、既存FunctionのLIVEコード・ARN、Lambda@EdgeのバージョンARNを保存する。ローカル作業ファイルはGitに含めない。
2. DefaultCacheBehaviorとOrderedCacheBehaviorsについて、`/keiko`, `/keiko/`, `/renseikai`, `/renseikai/` に実際に一致するBehaviorを確認する。URI書き換えでBehavior・originは再選択されない。S3 origin／OACへ到達することを確認する。
3. 各BehaviorのFunctionAssociations／LambdaFunctionAssociationsを確認する。既存viewer-request Functionを上書きしない。同じviewerイベントでCloudFront FunctionとLambda@Edgeは併用できない。既存処理があれば統合版を別途レビューし、元の処理のテストも行う。未調査のまま関連付けない。
4. CachePolicyのMin/Default/Max TTL、クエリのキャッシュキー・転送設定、OriginRequestPolicy、ResponseHeadersPolicy（CSPを含む）、CustomErrorResponsesの403/404 TTLを記録する。未知URLをトップへ200で返す設定に頼らない。クエリ追加だけでキャッシュ回避できるとは仮定しない。
5. PublisherのPutObjectとOACのGetObjectがカテゴリキーを許可すること、EVENTS_KEY=events.json、SITE_URL、HTML公開有効を確認する。S3 Block Public Accessを解除しない。

## 適用順序

1. 最新main、PR merge済み、全テスト・publish dry-run成功を確認する。
2. FunctionをDEVELOPMENTで作成／更新し、下記相当の入力を `aws cloudfront test-function` で確認する。これは実際のCloudFrontランタイム検証であり、ローカルChromiumでのJSテストとは別に実施する。
3. Publisherコードを更新する前に、今回のテンプレートから公開原本events.jsonを使ってカテゴリHTMLを生成し、カテゴリ2キーだけをS3へ配置する（この段階でも本番操作許可が必要）。S3原本と `/keiko/index.html`, `/renseikai/index.html` の配信を確認する。トップや定期処理を先に更新し、存在しないURLへ誘導しない。
4. FunctionをLIVEへpublishし、確認済みのBehaviorにviewer-requestとして関連付ける。既存設定を保持し、最新ETagを使う。DistributionがDeployedになるまで待つ。
5. `/keiko?tag=a&tag=b&empty=` の301 Location、`/keiko/`・`/renseikai/` の200と対応HTML、対象外URL不変を確認する。GETとHEADを確認する。
6. 公開runbookに従いPublisherを更新・publish_onlyで実行し、共通JSON・カテゴリ2ページ・トップ・sitemapを同じpayloadで更新する。自動スクレイパーやStep Functions全体を実行する必要はない。
7. S3原本の3ページ一致と、CloudFront経由のtitle・canonical・カード・JSON取得・リンク遷移を確認する。即時反映が必要な場合だけ許可の範囲でInvalidationを行う。候補は `/`, `/index.html`, `/events.json`, `/sitemap.xml`, `/keiko`, `/keiko/`, `/keiko/index.html`, `/renseikai`, `/renseikai/`, `/renseikai/index.html`。クエリをキャッシュキーに含める場合は各バリアントも対象にする。

Functionテスト入力例:

```json
{"version":"1.0","context":{"eventType":"viewer-request"},"viewer":{"ip":"192.0.2.1"},"request":{"method":"GET","uri":"/keiko","headers":{},"querystring":{"tag":{"value":"a","multiValue":[{"value":"a"},{"value":"b"}]},"empty":{"value":""}}}}
```

200の検証はstatusだけでなくカテゴリ固有canonicalとカードを確認する。S3/CloudFrontの公開イベント件数は時点によって変わるため固定総数で判定しない。

## 戻し方

- Function導入中の不具合: 保存した元の関連付けへ戻すか、カテゴリ処理を含まない元のFunctionコードを新しいETagで復元・publishする。Deployed完了後に既存URLへの影響が解消したことを確認する。初回関連付けを外すとカテゴリの末尾スラッシュURLは使えなくなるため、トップのリンク公開前に行う。
- トップ公開後の全面rollback: 先に直前の正常なPublisherコード・トップ・sitemapを復元し、新しいカテゴリへのリンクを除く。カテゴリオブジェクトとURL処理は既存リンク利用者のため可能なら残す。URL処理自体に問題があれば、リンク除去の反映確認後に元の関連付けへ戻す。
- S3原本・CloudFrontの双方を確認し、必要なパスだけキャッシュを失効させる。既存の定期Publisherが変更を再公開しないようコードも戻す。手動データを削除したり、S3公開設定を変更したりしない。

## 関東・東京都の地域ページを追加する初回手順

マージと本番適用の明示指示後、上記の適用前確認を地域2URLにも行う。旧Functionは地域のディレクトリURLを処理しないため、Publisher更新だけでは公開完了にならない。

1. 最新main・clean・upstream一致を確認し、公開S3原本のevents.jsonから生成CLIで5ページを生成する。スクレイパーを実行する必要はない。
2. `site.css`、`calendar.css`、`calendar-core.js`、`regional-calendar.js`と地域2キーを先にS3へ配置する。写真・フォント・既存アセットの配信も確認する。入口リンクを含むトップ／カテゴリはまだ更新しない。
3. `/area/kanto/index.html`と`/area/tokyo/index.html`のS3原本およびCloudFrontで、各地域固有のcanonical・件数・更新日時・静的カード・JSアセットを確認する。200だけでトップへの誤転送を見逃さない。
4. 保存した現行LIVEコードと関連付けに合わせ、新ルートを統合する。DEVELOPMENTでGET／HEADの地域2パス、末尾スラッシュ・直接index.html、重複クエリ・空値、既存カテゴリ、対象外URL／メソッドを`aws cloudfront test-function`で確認する。ローカルブラウザテストで代用しない。
5. LIVEへpublish・確認済みBehaviorへ適用し、Deployed後に地域の301／200と正常なカード表示を確認する。既存カテゴリ・OAC・他のFunction／Lambda@Edge処理を維持する。
6. 通常のpublish_only手順でPublisherを更新・実行し、共通JSON・地域2ページ・既存3ページ・sitemapを更新する。公開スクリプトの5ページ一致検証を確認する。
7. 実際の地域ページで一覧／月／土日、公式リンク、JS無効、スマートフォンを確認する。必要な場合だけ、新しい`/area/kanto`・`/area/kanto/`・`/area/kanto/index.html`と東京の対応パス、既存入口・アセットをキャッシュ失効の対象へ加える。

地域機能だけを戻す場合は、先に直前のPublisher・入口HTML・sitemapへ戻す。地域のオブジェクトとURL処理は可能なら残し、Function自体を戻す場合も既存カテゴリの処理・関連付けを維持する。定期Publisherが新しい入口を再公開しないことも確認する。

## 仕様の根拠

- [AWS: Default root object](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DefaultRootObject.html)
- [AWS: URL書き換えの例](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/example_cloudfront_functions_url_rewrite_single_page_apps_section.html)
- [AWS: Function event構造・querystring・multiValue](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/functions-event-structure.html)
- [AWS: edge functionの制約](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/edge-function-restrictions-all.html)

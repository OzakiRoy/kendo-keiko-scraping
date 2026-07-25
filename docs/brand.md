# 剣道稽古ナビのブランド資産

## 正式名称

```text
剣道稽古ナビ
```

英語表記:

```text
KENDO KEIKO NAVI
```

サブコピー:

```text
参加できる稽古会を、日付・地域・参加条件から探す
```

ドメイン `kendo-keiko.com` は変更しない。検索結果では、オープン稽古会・合同稽古会を探せるサイトであることが分かる表現を残す。

## 色

| 用途 | 色 |
|---|---|
| 墨色 | `#1b1b1b` |
| 朱色 | `#8c1d24` |
| 紙色 | `#f3f1ec` |
| 白地 | `#fffdfa` |

## 公開資産

```text
public/favicon.svg
public/favicon.ico
public/favicon-32x32.png
public/apple-touch-icon.png
public/icon-192.png
public/icon-512.png
public/ogp.png
public/site.webmanifest
```

faviconは朱色の円形に白抜きの「稽」を置き、小さい表示でも識別しやすい落款風デザインとする。OGP画像は1200×630ピクセルとする。

## 再生成

ブランド資産はGitへコミットし、通常のLambda実行時には画像生成しない。再生成する場合だけ、ローカル環境へPillowと日本語フォントを用意して実行する。

```bash
python scripts/generate_brand_assets.py
```

PillowはLambdaの実行依存ではないため、`requirements.txt` へ追加しない。

## 公開方法

Publisher Lambdaは、`events.json`、`index.html`、`sitemap.xml` と同時にブランド資産をS3へ配置する。Lambda ZIPには `public/index.html` とすべてのブランド資産を含める。

本番反映後は、最低限次を確認する。

- ブラウザタブにfaviconが表示される
- ヘッダーが「剣道稽古ナビ」になっている
- HTMLのtitle、description、OGP、Twitter Cardが統一されている
- `https://kendo-keiko.com/ogp.png` が表示できる
- モバイルとデスクトップでロゴと見出しが崩れない
- canonical、robots.txt、sitemap.xmlが維持されている

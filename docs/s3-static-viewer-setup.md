# S3 静的ビューア配置手順

## 目的

ローカルで確認していた `public/index.html` をS3に配置し、同じS3バケット上の `events.json` を読み込める構成にする。

MVPではS3を直接公開せず、Block Public Accessを維持する。  
ブラウザ公開は次フェーズの CloudFront + OAC で行う。

## 構成

```text
S3 bucket
  ├── index.html
  └── events.json
```

# CloudFront + OAC セットアップ手順

## 目的

S3 に配置した静的ビューアを、S3 を公開せずに CloudFront 経由でブラウザ公開する。

MVP段階では、以下の構成にする。

```text
Browser
  ↓
CloudFront
  ↓ OAC
Private S3 bucket
  ├── index.html
  └── events.json
```

## 方針

- S3 Bucket は直接公開しない
- S3 Block Public Access は有効のままにする
- CloudFront OAC を使って、CloudFront からのアクセスだけ S3 に許可する
- まずは CloudFront のデフォルトドメインで公開確認する
- 独自ドメイン、ACM証明書、WAF は次フェーズで検討する

## 前提

以下が完了していること。

- S3 バケットが作成済み
- S3 に `index.html` が配置済み
- S3 に `events.json` が配置済み
- S3 Block Public Access が有効
- Lambda から `events.json` をS3へ出力できる

## 1. 変数を設定する

```bash
export AWS_REGION=ap-northeast-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

export EVENTS_BUCKET="kendo-keiko-site-${ACCOUNT_ID}-${AWS_REGION}"
export ORIGIN_ID="s3-kendo-keiko-site"
export OAC_NAME="kendo-keiko-site-oac"
export COMMENT="Kendo Keiko static site"
```

必要に応じて AWS profile を指定する。

```bash
export AWS_PROFILE=your-profile-name
```

## 2. S3 の中身を確認する

```bash
aws s3 ls "s3://${EVENTS_BUCKET}/"
```

期待値:

```text
events.json
index.html
```

## 3. CloudFront OAC を作成する

```bash
OAC_ID=$(aws cloudfront create-origin-access-control \
  --origin-access-control-config "Name=${OAC_NAME},Description=OAC for ${EVENTS_BUCKET},SigningProtocol=sigv4,SigningBehavior=always,OriginAccessControlOriginType=s3" \
  --query 'OriginAccessControl.Id' \
  --output text)

echo "OAC_ID=${OAC_ID}"
```

## 4. CloudFront の Managed Policy ID を取得する

キャッシュポリシーは `Managed-CachingOptimized` を使う。

```bash
CACHE_POLICY_ID=$(aws cloudfront list-cache-policies \
  --type managed \
  --query "CachePolicyList.Items[?CachePolicy.CachePolicyConfig.Name=='Managed-CachingOptimized'].CachePolicy.Id | [0]" \
  --output text)

echo "CACHE_POLICY_ID=${CACHE_POLICY_ID}"
```

レスポンスヘッダーポリシーは `Managed-SecurityHeadersPolicy` を使う。

```bash
RESPONSE_HEADERS_POLICY_ID=$(aws cloudfront list-response-headers-policies \
  --type managed \
  --query "ResponseHeadersPolicyList.Items[?ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name=='Managed-SecurityHeadersPolicy'].ResponseHeadersPolicy.Id | [0]" \
  --output text)

echo "RESPONSE_HEADERS_POLICY_ID=${RESPONSE_HEADERS_POLICY_ID}"
```

`None` になっていないことを確認する。

```bash
echo "${CACHE_POLICY_ID}"
echo "${RESPONSE_HEADERS_POLICY_ID}"
```

## 5. CloudFront Distribution 設定ファイルを作成する

```bash
cat > cloudfront-distribution-config.json <<EOF
{
  "CallerReference": "kendo-keiko-site-$(date +%s)",
  "Comment": "${COMMENT}",
  "Enabled": true,
  "DefaultRootObject": "index.html",
  "PriceClass": "PriceClass_100",
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "${ORIGIN_ID}",
        "DomainName": "${EVENTS_BUCKET}.s3.${AWS_REGION}.amazonaws.com",
        "OriginAccessControlId": "${OAC_ID}",
        "S3OriginConfig": {
          "OriginAccessIdentity": ""
        }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "${ORIGIN_ID}",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": {
      "Quantity": 2,
      "Items": ["GET", "HEAD"],
      "CachedMethods": {
        "Quantity": 2,
        "Items": ["GET", "HEAD"]
      }
    },
    "Compress": true,
    "CachePolicyId": "${CACHE_POLICY_ID}",
    "ResponseHeadersPolicyId": "${RESPONSE_HEADERS_POLICY_ID}"
  }
}
EOF
```

## 6. CloudFront Distribution を作成する

```bash
aws cloudfront create-distribution \
  --distribution-config file://cloudfront-distribution-config.json \
  > cloudfront-create-output.json
```

`jq` がある場合:

```bash
DISTRIBUTION_ID=$(jq -r '.Distribution.Id' cloudfront-create-output.json)
CLOUDFRONT_DOMAIN=$(jq -r '.Distribution.DomainName' cloudfront-create-output.json)

echo "DISTRIBUTION_ID=${DISTRIBUTION_ID}"
echo "CLOUDFRONT_DOMAIN=${CLOUDFRONT_DOMAIN}"
```

`jq` がない場合は、以下で内容を確認する。

```bash
cat cloudfront-create-output.json | head -80
```

必要に応じて手動で `DISTRIBUTION_ID` と `CLOUDFRONT_DOMAIN` を設定する。

```bash
export DISTRIBUTION_ID=xxxxxxxxxxxxxx
export CLOUDFRONT_DOMAIN=xxxxxxxxxxxxxx.cloudfront.net
```

## 7. S3 バケットポリシーを作成する

S3 は非公開のまま、作成した CloudFront Distribution からの `s3:GetObject` のみ許可する。

```bash
cat > s3-cloudfront-oac-bucket-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowCloudFrontServicePrincipalReadOnly",
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudfront.amazonaws.com"
      },
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${EVENTS_BUCKET}/*",
      "Condition": {
        "StringEquals": {
          "AWS:SourceArn": "arn:aws:cloudfront::${ACCOUNT_ID}:distribution/${DISTRIBUTION_ID}"
        }
      }
    }
  ]
}
EOF
```

## 8. S3 バケットポリシーを適用する

```bash
aws s3api put-bucket-policy \
  --bucket "${EVENTS_BUCKET}" \
  --policy file://s3-cloudfront-oac-bucket-policy.json
```

確認する。

```bash
aws s3api get-bucket-policy \
  --bucket "${EVENTS_BUCKET}" \
  --query Policy \
  --output text
```

## 9. Distribution のデプロイ完了を待つ

CloudFront の反映には数分かかる。

```bash
aws cloudfront wait distribution-deployed \
  --id "${DISTRIBUTION_ID}"
```

## 10. CloudFront 経由で確認する

トップページ。

```bash
curl -I "https://${CLOUDFRONT_DOMAIN}/"
```

期待値:

```text
HTTP/2 200
```

`events.json`。

```bash
curl -I "https://${CLOUDFRONT_DOMAIN}/events.json"
```

内容確認。

```bash
curl -s "https://${CLOUDFRONT_DOMAIN}/events.json" | head -40
```

ブラウザで開く。

```text
https://<CLOUDFRONT_DOMAIN>/
```

例:

```text
https://xxxxxxxxxxxxxx.cloudfront.net/
```

## 11. S3 直アクセスが拒否されることを確認する

S3 は非公開のため、直接アクセスは拒否されるのが正しい。

```bash
curl -I "https://${EVENTS_BUCKET}.s3.${AWS_REGION}.amazonaws.com/index.html"
```

期待値:

```text
HTTP/1.1 403 Forbidden
```

## 12. Distribution 情報を確認する

```bash
aws cloudfront get-distribution \
  --id "${DISTRIBUTION_ID}" \
  --query 'Distribution.{Id:Id,DomainName:DomainName,Status:Status,Enabled:DistributionConfig.Enabled}'
```

## 13. index.html / events.json を更新した場合

S3にファイルをアップロードし直す。

```bash
aws s3 cp public/index.html "s3://${EVENTS_BUCKET}/index.html" \
  --content-type "text/html; charset=utf-8" \
  --cache-control "max-age=300" \
  --region "${AWS_REGION}"
```

`events.json` は Lambda が定期実行で更新する。

すぐに CloudFront キャッシュを削除したい場合は invalidation を作成する。

```bash
aws cloudfront create-invalidation \
  --distribution-id "${DISTRIBUTION_ID}" \
  --paths "/index.html" "/events.json" "/"
```

## 14. Git管理しないローカル作業ファイル

以下はローカル作業用のため、Git管理しない。

```text
cloudfront-distribution-config.json
cloudfront-create-output.json
s3-cloudfront-oac-bucket-policy.json
```

`.gitignore` に追加する。

```bash
cat >> .gitignore <<'EOF'

# local CloudFront setup files
cloudfront-distribution-config.json
cloudfront-create-output.json
s3-cloudfront-oac-bucket-policy.json
EOF
```

## 15. Gitに記録する

```bash
git add docs/cloudfront-oac-setup.md .gitignore
git commit -m "Add CloudFront OAC setup guide"
git push
```

## 16. IssueをCloseする

Issue番号が `3` の場合。

```bash
gh issue close 3 --comment "CloudFront distribution with OAC is configured. The S3 bucket remains private, and the static viewer is available through the CloudFront domain."
```

## 現時点の構成

```text
EventBridge Scheduler
  ↓
Lambda
  ↓
DynamoDB
  ↓
S3 events.json
  ↓
CloudFront + OAC
  ↓
Browser
```

## 次の改善候補

- 独自ドメインを取得する
- ACM証明書を us-east-1 で作成する
- CloudFront に独自ドメインを設定する
- AWS WAF を CloudFront に関連付ける
- Security Headers をより厳格にする
- Terraform 化する

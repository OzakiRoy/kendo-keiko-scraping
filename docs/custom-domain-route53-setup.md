# Custom Domain + Route 53 + CloudFront セットアップ手順

## 目的

CloudFront + OAC で公開済みの静的ビューアを、独自ドメイン `kendo-keiko.com` で HTTPS 公開する。

MVP段階では、以下の構成にする。

```text
Browser
  ↓
https://kendo-keiko.com/
https://www.kendo-keiko.com/
  ↓
Route 53 Alias
  ↓
CloudFront
  ↓ OAC
Private S3 bucket
  ├── index.html
  └── events.json
```

## 方針

- ドメインは `kendo-keiko.com` を使用する
- DNSは Route 53 の Public Hosted Zone で管理する
- CloudFront 用 ACM 証明書は `us-east-1` で発行する
- S3 は引き続き非公開にする
- CloudFront + OAC 経由でのみ S3 のファイルを配信する
- apex domain と www の両方を CloudFront に向ける

## 前提

以下が完了していること。

- S3 バケットが作成済み
- S3 に `index.html` と `events.json` が配置済み
- S3 Block Public Access が有効
- CloudFront Distribution が作成済み
- CloudFront OAC が設定済み
- CloudFront 経由で静的ビューアが表示できる
- AWS CLI / jq が使用できる

## 1. 変数を設定する

```bash
export AWS_REGION=ap-northeast-1
export DOMAIN="kendo-keiko.com"
export WWW_DOMAIN="www.${DOMAIN}"
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

既存の CloudFront Distribution ID を設定する。

```bash
export DISTRIBUTION_ID="xxxxxxxxxxxxxx"
```

Distribution ID が不明な場合は一覧から確認する。

```bash
aws cloudfront list-distributions \
  --query 'DistributionList.Items[].{Id:Id,DomainName:DomainName,Comment:Comment,Enabled:Enabled}' \
  --output table
```

## 2. ドメイン空き確認

Route 53 Domains の空き確認は `us-east-1` で実行する。

```bash
aws route53domains check-domain-availability \
  --region us-east-1 \
  --domain-name "${DOMAIN}"
```

期待値:

```json
{
  "Availability": "AVAILABLE"
}
```

## 3. ドメインを登録する

ドメイン登録は課金と登録者情報の入力を伴うため、AWSコンソールから行う。

```text
Route 53
  ↓
Registered domains
  ↓
Register domains
  ↓
kendo-keiko.com を検索
  ↓
登録情報を入力
  ↓
購入
```

登録後、Route 53 に Public Hosted Zone が作成されていることを確認する。

```bash
aws route53 list-hosted-zones-by-name \
  --dns-name "${DOMAIN}."
```

Hosted Zone ID を取得する。

```bash
export HOSTED_ZONE_ID=$(aws route53 list-hosted-zones-by-name \
  --dns-name "${DOMAIN}." \
  --query "HostedZones[?Name=='${DOMAIN}.' && Config.PrivateZone==\`false\`].Id | [0]" \
  --output text | sed 's#/hostedzone/##')

echo "${HOSTED_ZONE_ID}"
```

空でなければOK。

## 4. ACM証明書を作成する

CloudFront に設定する ACM 証明書は、必ず `us-east-1` で作成する。

apex domain と www の両方を証明書に含める。

```bash
export CERT_ARN=$(aws acm request-certificate \
  --region us-east-1 \
  --domain-name "${DOMAIN}" \
  --subject-alternative-names "${WWW_DOMAIN}" \
  --validation-method DNS \
  --query CertificateArn \
  --output text)

echo "${CERT_ARN}"
```

### 変数未設定時の注意

`WWW_DOMAIN` が空のまま実行すると、以下のようなエラーになる。

```text
Parameter validation failed:
Invalid length for parameter SubjectAlternativeNames[0], value: 0, valid min length: 1
```

その場合は、変数をセットし直す。

```bash
export DOMAIN="kendo-keiko.com"
export WWW_DOMAIN="www.${DOMAIN}"

echo "DOMAIN=${DOMAIN}"
echo "WWW_DOMAIN=${WWW_DOMAIN}"
```

## 5. ACM DNS検証レコードを取得する

```bash
aws acm describe-certificate \
  --region us-east-1 \
  --certificate-arn "${CERT_ARN}" \
  --query 'Certificate.DomainValidationOptions[].ResourceRecord' \
  --output json > cert-validation-records.json

cat cert-validation-records.json
```

## 6. DNS検証レコードをRoute 53に追加する

`jq` を使って Route 53 用の change batch を作成する。

```bash
jq 'unique_by(.Name, .Type, .Value)
  | {
      Changes: [
        .[] |
        {
          Action: "UPSERT",
          ResourceRecordSet: {
            Name: .Name,
            Type: .Type,
            TTL: 300,
            ResourceRecords: [
              {
                Value: .Value
              }
            ]
          }
        }
      ]
    }' cert-validation-records.json > cert-validation-change-batch.json
```

Route 53 に反映する。

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id "${HOSTED_ZONE_ID}" \
  --change-batch file://cert-validation-change-batch.json
```

ACM証明書が発行されるまで待つ。

```bash
aws acm wait certificate-validated \
  --region us-east-1 \
  --certificate-arn "${CERT_ARN}"
```

状態を確認する。

```bash
aws acm describe-certificate \
  --region us-east-1 \
  --certificate-arn "${CERT_ARN}" \
  --query 'Certificate.Status'
```

期待値:

```text
"ISSUED"
```

## 7. CloudFrontの現在設定を取得する

```bash
aws cloudfront get-distribution-config \
  --id "${DISTRIBUTION_ID}" \
  > cf-config-output.json
```

ETag を取得する。

```bash
export ETAG=$(jq -r '.ETag' cf-config-output.json)
echo "${ETAG}"
```

## 8. CloudFront更新用JSONを作成する

CloudFront に以下を設定する。

- Alternate domain names
  - `kendo-keiko.com`
  - `www.kendo-keiko.com`
- ACM証明書
  - `CERT_ARN`
- TLS minimum protocol
  - `TLSv1.2_2021`

```bash
jq '.DistributionConfig
  | .Aliases = {
      "Quantity": 2,
      "Items": [env.DOMAIN, env.WWW_DOMAIN]
    }
  | .ViewerCertificate = {
      "ACMCertificateArn": env.CERT_ARN,
      "SSLSupportMethod": "sni-only",
      "MinimumProtocolVersion": "TLSv1.2_2021",
      "Certificate": env.CERT_ARN,
      "CertificateSource": "acm"
    }' cf-config-output.json > cf-updated-config.json
```

中身を確認する。

```bash
jq '.Aliases, .ViewerCertificate' cf-updated-config.json
```

## 9. CloudFrontを更新する

```bash
aws cloudfront update-distribution \
  --id "${DISTRIBUTION_ID}" \
  --if-match "${ETAG}" \
  --distribution-config file://cf-updated-config.json \
  > cf-update-output.json
```

反映完了を待つ。

```bash
aws cloudfront wait distribution-deployed \
  --id "${DISTRIBUTION_ID}"
```

CloudFront ドメインを取得する。

```bash
export CLOUDFRONT_DOMAIN=$(aws cloudfront get-distribution \
  --id "${DISTRIBUTION_ID}" \
  --query 'Distribution.DomainName' \
  --output text)

echo "${CLOUDFRONT_DOMAIN}"
```

## 10. Route 53 Aliasレコードを作成する

CloudFront Distribution に向ける Alias レコードを作成する。

対象:

- `kendo-keiko.com` A
- `kendo-keiko.com` AAAA
- `www.kendo-keiko.com` A
- `www.kendo-keiko.com` AAAA

CloudFront Distribution の AliasTarget HostedZoneId は `Z2FDTNDATAQYW2` を使用する。

```bash
cat > route53-cloudfront-alias-records.json <<EOF
{
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${DOMAIN}.",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "Z2FDTNDATAQYW2",
          "DNSName": "${CLOUDFRONT_DOMAIN}.",
          "EvaluateTargetHealth": false
        }
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${DOMAIN}.",
        "Type": "AAAA",
        "AliasTarget": {
          "HostedZoneId": "Z2FDTNDATAQYW2",
          "DNSName": "${CLOUDFRONT_DOMAIN}.",
          "EvaluateTargetHealth": false
        }
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${WWW_DOMAIN}.",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "Z2FDTNDATAQYW2",
          "DNSName": "${CLOUDFRONT_DOMAIN}.",
          "EvaluateTargetHealth": false
        }
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${WWW_DOMAIN}.",
        "Type": "AAAA",
        "AliasTarget": {
          "HostedZoneId": "Z2FDTNDATAQYW2",
          "DNSName": "${CLOUDFRONT_DOMAIN}.",
          "EvaluateTargetHealth": false
        }
      }
    }
  ]
}
EOF
```

Route 53 に反映する。

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id "${HOSTED_ZONE_ID}" \
  --change-batch file://route53-cloudfront-alias-records.json
```

## 11. DNS確認

```bash
dig "${DOMAIN}"
dig "${WWW_DOMAIN}"
```

必要に応じて Google DNS などを指定して確認する。

```bash
dig @8.8.8.8 "${DOMAIN}"
dig @8.8.8.8 "${WWW_DOMAIN}"
```

## 12. HTTPS確認

```bash
curl -I "https://${DOMAIN}/"
curl -I "https://${WWW_DOMAIN}/"
```

期待値:

```text
HTTP/2 200
```

ブラウザでも確認する。

```text
https://kendo-keiko.com/
https://www.kendo-keiko.com/
```

## 13. よくあるエラー

### SubjectAlternativeNamesが空

原因:

```text
WWW_DOMAIN が未設定
```

確認:

```bash
echo "DOMAIN=${DOMAIN}"
echo "WWW_DOMAIN=${WWW_DOMAIN}"
```

修正:

```bash
export DOMAIN="kendo-keiko.com"
export WWW_DOMAIN="www.${DOMAIN}"
```

### InvalidViewerCertificate

主な原因:

```text
- CERT_ARN が us-east-1 の証明書ではない
- 証明書が ISSUED になっていない
- 証明書に kendo-keiko.com / www.kendo-keiko.com が含まれていない
- DOMAIN / WWW_DOMAIN 変数が空
```

### CNAMEAlreadyExists

原因:

```text
指定したドメインが別の CloudFront Distribution にすでに紐づいている
```

### 独自ドメインで403

確認ポイント:

```text
- CloudFront から S3 へは OAC でアクセスできているか
- S3 bucket policy に対象 Distribution の ARN が入っているか
- S3上に index.html / events.json が存在するか
```

## 14. Git管理しないローカル作業ファイル

以下はローカル作業用のため、Git管理しない。

```text
cert-validation-records.json
cert-validation-change-batch.json
cf-config-output.json
cf-updated-config.json
cf-update-output.json
route53-cloudfront-alias-records.json
```

`.gitignore` に追加する。

```bash
cat >> .gitignore <<'EOF'

# local custom domain setup files
cert-validation-records.json
cert-validation-change-batch.json
cf-config-output.json
cf-updated-config.json
cf-update-output.json
route53-cloudfront-alias-records.json
EOF
```

## 15. Gitに記録する

```bash
git add docs/custom-domain-route53-setup.md .gitignore
git commit -m "Add custom domain Route 53 setup guide"
git push
```

## 16. IssueをCloseする

対象Issue番号に合わせて実行する。

例: Issue番号が `4` の場合。

```bash
gh issue close 4 --comment "Configured kendo-keiko.com with Route 53, ACM, and CloudFront. The site is now available over HTTPS using the custom domain."
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
Route 53 Alias
  ↓
https://kendo-keiko.com/
```

## 次の改善候補

- サイトの見た目を整える
- 免責事項・出典表示・削除依頼窓口を追加する
- `www` を apex にリダイレクトする
- AWS WAF を CloudFront に関連付ける
- CloudFrontログやアクセス分析を検討する
- Terraform化する

#!/usr/bin/env bash
# Deploy the Clerk Assistant website (aws/clerk_site) to the stk-clerk-site Lambda
# and connect it to the AgentCore "clerk" runtime.
#
#   ./scripts/deploy_site.sh            deploy
#   ./scripts/deploy_site.sh rollback   restore the most recent backup
#
# Each deploy first saves the Lambda's current code to aws/clerk_site/backups/.
set -euo pipefail

REGION="us-west-2"
FUNCTION="stk-clerk-site"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE="$ROOT/aws/clerk_site"
BACKUPS="$SITE/backups"

say() { printf '\n== %s\n' "$*"; }

if [[ "${1:-}" == "rollback" ]]; then
  latest="$(ls -t "$BACKUPS"/*.zip 2>/dev/null | head -1 || true)"
  [[ -n "$latest" ]] || { echo "No backups in $BACKUPS"; exit 1; }
  say "Restoring $latest"
  aws lambda update-function-code --region "$REGION" --function-name "$FUNCTION" \
    --zip-file "fileb://$latest" --query 'LastUpdateStatus' --output text
  aws lambda wait function-updated --region "$REGION" --function-name "$FUNCTION"
  echo "Restored. (Timeout, environment and IAM changes from the deploy were left in place; they're harmless to the old code.)"
  exit 0
fi

say "Finding the AgentCore runtime"
ARNS="$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
  --query "agentRuntimes[?contains(agentRuntimeName, 'clerk')].agentRuntimeArn" --output text)"
count="$(wc -w <<<"$ARNS" | tr -d ' ')"
[[ "$count" == "1" ]] || { echo "Expected one runtime with 'clerk' in its name, found $count: $ARNS"; exit 1; }
RUNTIME_ARN="$ARNS"
echo "$RUNTIME_ARN"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
FUNCTION_ARN="arn:aws:lambda:$REGION:$ACCOUNT:function:$FUNCTION"
ROLE="$(aws lambda get-function-configuration --region "$REGION" --function-name "$FUNCTION" \
  --query Role --output text | awk -F/ '{print $NF}')"

say "Backing up the current Lambda code"
mkdir -p "$BACKUPS"
backup="$BACKUPS/$FUNCTION-$(date +%Y%m%d-%H%M%S).zip"
url="$(aws lambda get-function --region "$REGION" --function-name "$FUNCTION" --query Code.Location --output text)"
curl -sSfL "$url" -o "$backup"
echo "$backup"

say "Building the package (handler, page, current boto3)"
build="$(mktemp -d)"
trap 'rm -rf "$build"' EXIT
uv pip install --quiet --python 3.12 --target "$build/pkg" boto3
cp "$SITE/handler.py" "$SITE/index.html" "$build/pkg/"
(cd "$build/pkg" && zip -qr "$build/site.zip" .)
ls -lh "$build/site.zip" | awk '{print $5, $NF}'

say "Granting the Lambda access to the agent (inline policy stk-clerk-agent on role $ROLE)"
cat > "$build/policy.json" <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeClerkAgent",
      "Effect": "Allow",
      "Action": "bedrock-agentcore:InvokeAgentRuntime",
      "Resource": ["$RUNTIME_ARN", "$RUNTIME_ARN/*"]
    },
    {
      "Sid": "StartBackgroundRun",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "$FUNCTION_ARN"
    },
    {
      "Sid": "ClerkTables",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
      "Resource": [
        "arn:aws:dynamodb:$REGION:$ACCOUNT:table/AllowedPhones",
        "arn:aws:dynamodb:$REGION:$ACCOUNT:table/ClerkQuestions"
      ]
    }
  ]
}
POLICY
aws iam put-role-policy --role-name "$ROLE" --policy-name stk-clerk-agent \
  --policy-document "file://$build/policy.json"

say "Setting timeout (120s) and environment"
aws lambda update-function-configuration --region "$REGION" --function-name "$FUNCTION" \
  --timeout 120 \
  --environment "Variables={QUESTIONS_TABLE=ClerkQuestions,PHONES_TABLE=AllowedPhones,SECRET_ID=stk-clerk/cursor,AGENT_RUNTIME_ARN=$RUNTIME_ARN}" \
  --query 'LastUpdateStatus' --output text
aws lambda wait function-updated --region "$REGION" --function-name "$FUNCTION"

say "Uploading the new code"
aws lambda update-function-code --region "$REGION" --function-name "$FUNCTION" \
  --zip-file "fileb://$build/site.zip" --query 'LastUpdateStatus' --output text
aws lambda wait function-updated --region "$REGION" --function-name "$FUNCTION"

say "Smoke test"
sleep 3
curl -sS https://clerk.ginkgointernational.com/api/me; echo
echo
echo "Deployed. Expect {\"signedIn\": false} above. If anything's wrong: ./scripts/deploy_site.sh rollback"

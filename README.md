# StkClerkAIbot

The Clerk Assistant for the West Jordan Utah Copper Hills Stake, at
https://clerk.ginkgointernational.com. Clerks and executive secretaries sign in
with their phone number and ask how-to questions; answers come from the stake's
clerk knowledge base (`docs/stake-clerk-training-manual.md`), with the General
Handbook as the authority.

See `docs/PURPOSE.md` for what the assistant is for and the principles it follows.

## How it fits together

```
clerk.ginkgointernational.com  ->  CloudFront  ->  API Gateway  ->  Lambda stk-clerk-site
                                                                      (aws/clerk_site/)
   sign-in: AllowedPhones table          questions: ClerkQuestions table
                                         background run -> AgentCore runtime "clerk"
                                                           (agent/, Claude on Bedrock)
```

Everything runs in AWS account 730667687685, region us-west-2.

## Repository layout

| Path | What it is |
|---|---|
| `agent/` | The AI agent: `clerk_agent.py`, its rules in `instructions.md`, and tests in `tests/` |
| `agentcore/` | AgentCore deployment config (CDK); uploads the knowledge base to S3 on each deploy |
| `aws/clerk_site/` | The website: `handler.py` (Lambda) and `index.html` |
| `scripts/clerkcontact.py` | Manage who can sign in. See `docs/clerkcontact.md` |
| `scripts/deploy_site.sh` | Deploy the website Lambda (with automatic backup and rollback) |
| `docs/` | The knowledge base, purpose and principles, and guides |

## Common tasks

**Manage who can sign in**: see [`docs/clerkcontact.md`](docs/clerkcontact.md).

**Update the knowledge base**: edit `docs/stake-clerk-training-manual.md`, then
deploy the agent (below). New questions use the new text right away.

**Change how the agent answers**: edit `agent/instructions.md`, run the tests, then deploy the agent.

**Run the agent tests** (about 22 questions, a few cents of Bedrock usage):
```bash
cd agent
AWS_REGION=us-west-2 uv run --no-project --with-requirements requirements.txt python tests/run_tests.py
```
Full answers are saved in `agent/tests/results/` (not committed).

**Deploy the agent** (needs `npm install -g @aws/agentcore` once):
```bash
agentcore deploy --region us-west-2
agentcore invoke --runtime clerk --region us-west-2 --payload '{"question": "When are the membership audits due?"}'
```

**Deploy the website**:
```bash
./scripts/deploy_site.sh            # backs up the current Lambda first
./scripts/deploy_site.sh rollback   # restore the most recent backup
```

**Look at logs when something fails**:
```bash
aws logs tail /aws/lambda/stk-clerk-site --region us-west-2 --since 30m
```
Failed questions also have an `errorDetail` field in the ClerkQuestions table.

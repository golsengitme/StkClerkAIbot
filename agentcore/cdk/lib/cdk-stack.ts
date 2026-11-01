import * as path from 'path';
import { AgentCoreApplication, type AgentCoreApplicationProps } from '@aws/agentcore-cdk';
import { CfnOutput, Stack, type StackProps } from 'aws-cdk-lib';
import { Asset } from 'aws-cdk-lib/aws-s3-assets';
import { Construct } from 'constructs';

export interface AgentCoreStackProps extends StackProps {
  /** Props for the AgentCore application, produced by transformAgentCoreJson from agentcore/agentcore.json. */
  application: AgentCoreApplicationProps;
}

/** Model the clerk agent uses. Change here (or set MODEL_ID) to switch models. */
const MODEL_ID = 'us.anthropic.claude-sonnet-4-6';

/**
 * The Copper Hills Stake Clerk Assistant.
 *
 * - Runtime "clerk" runs agent/clerk_agent.py (declared in agentcore/agentcore.json).
 * - The training manual (docs/stake-clerk-training-manual.md) is uploaded to S3 on
 *   every deploy; the agent reads it at startup. Edit the manual, run
 *   `agentcore deploy`, and new sessions use the new text.
 */
export class AgentCoreStack extends Stack {
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);
    this.application = new AgentCoreApplication(this, 'Application', props.application);

    // dist/lib -> cdk -> agentcore -> repo root
    const manualPath = path.join(__dirname, '..', '..', '..', '..', 'docs', 'stake-clerk-training-manual.md');
    const manual = new Asset(this, 'TrainingManual', { path: manualPath });

    const clerk = this.application.runtime('clerk');
    manual.grantRead(clerk);
    clerk.addEnvironmentVariable('MANUAL_S3_URI', manual.s3ObjectUrl);
    clerk.addEnvironmentVariable('MODEL_ID', MODEL_ID);

    new CfnOutput(this, 'ManualS3Uri', { value: manual.s3ObjectUrl });
  }
}

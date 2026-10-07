#!/usr/bin/env python3
# Motivation vs Logic
# Motivation: Produce the Quotient staging template for a later deploy.
# Logic: Pin account 255834078973 and ap-southeast-2, then synthesize
# StagingStack. This entrypoint does not call deploy.

import aws_cdk as cdk

from quotient.names import ACCOUNT, REGION
from quotient.stack import StagingStack

app = cdk.App()
StagingStack(
    app,
    "axion-meeting-staging",
    env=cdk.Environment(account=ACCOUNT, region=REGION),
    description=(
        "Quotient staging. Sydney VPC 10.40.0.0/16, Fargate, DynamoDB, S3, "
        "Cognito, and billing alarms. Does not reference Engine VPCs."
    ),
)
app.synth()

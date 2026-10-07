# Motivation vs Logic
# Motivation: Stop staging spend at $25 per day and $200 per month, and page
# when a stage lands on the dead-letter queue.
# Logic: One SNS topic plus an email subscription from the AlarmEmail
# parameter. Two cost budgets filter on the Project=axion-meeting-staging
# tag and notify that topic above 100 percent of actual spend. A CloudWatch
# alarm fires when the DLQ has a visible message. Budgets are account-level
# resources; the tag filter keeps Engine spend out of these ceilings.

from aws_cdk import Aws, CfnParameter, Duration, aws_budgets as budgets, aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions, aws_iam as iam, aws_sns as sns, aws_sqs as sqs
from constructs import Construct

from quotient.names import PREFIX


class BillingAlarms(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, dlq: sqs.IQueue) -> None:
        super().__init__(scope, construct_id)
        email = CfnParameter(
            self,
            "AlarmEmail",
            type="String",
            description="Email subscribed to Quotient staging billing alarms. Confirm the SNS subscription after deploy.",
            allowed_pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
            constraint_description="Must be an email address.",
        )
        email.override_logical_id("AlarmEmail")
        self.topic = sns.Topic(self, "Billing", topic_name=f"{PREFIX}-billing", display_name="Quotient staging billing")
        sns.CfnSubscription(
            self,
            "Email",
            topic_arn=self.topic.topic_arn,
            protocol="email",
            endpoint=email.value_as_string,
        )
        self.topic.add_to_resource_policy(
            iam.PolicyStatement(
                sid="BudgetsPublish",
                principals=[iam.ServicePrincipal("budgets.amazonaws.com")],
                actions=["sns:Publish"],
                resources=[self.topic.topic_arn],
                conditions={"StringEquals": {"aws:SourceAccount": Aws.ACCOUNT_ID}},
            )
        )
        self.topic.add_to_resource_policy(
            iam.PolicyStatement(
                sid="CloudWatchPublish",
                principals=[iam.ServicePrincipal("cloudwatch.amazonaws.com")],
                actions=["sns:Publish"],
                resources=[self.topic.topic_arn],
                conditions={"StringEquals": {"aws:SourceAccount": Aws.ACCOUNT_ID}},
            )
        )
        self._budget("Daily", f"{PREFIX}-daily", "DAILY", 25)
        self._budget("Monthly", f"{PREFIX}-monthly", "MONTHLY", 200)
        alarm = cloudwatch.Alarm(
            self,
            "DeadLetter",
            alarm_name=f"{PREFIX}-dlq",
            metric=dlq.metric_approximate_number_of_messages_visible(
                period=Duration.minutes(1),
                statistic="Maximum",
            ),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="A Quotient stage exhausted SQS receives.",
        )
        alarm.add_alarm_action(cw_actions.SnsAction(self.topic))

    def _budget(self, construct_id: str, name: str, time_unit: str, amount: int) -> None:
        budgets.CfnBudget(
            self,
            construct_id,
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=name,
                budget_type="COST",
                time_unit=time_unit,
                budget_limit=budgets.CfnBudget.SpendProperty(amount=amount, unit="USD"),
                cost_filters={"TagKeyValue": [f"user:Project${PREFIX}"]},
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type="ACTUAL",
                        threshold=100,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            address=self.topic.topic_arn,
                            subscription_type="SNS",
                        )
                    ],
                )
            ],
        )

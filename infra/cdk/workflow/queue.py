# Motivation vs Logic
# Motivation: Give the coarse DAG a queue whose depth can scale workers from
# zero, and a dead-letter queue when a stage cannot be acknowledged.
# Logic: Standard queue, 5 minute visibility, long poll 20 seconds, SSL only.
# Eight receives then the DLQ. The worker must extend visibility and must not
# delete the message until SendTaskSuccess or SendTaskFailure, so in-flight
# depth keeps the desired count above zero for the life of the stage.

from aws_cdk import Duration, aws_sqs as sqs
from constructs import Construct

from quotient.names import PREFIX


class WorkQueue(Construct):
    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)
        self.dlq = sqs.Queue(
            self,
            "Dead",
            queue_name=f"{PREFIX}-dlq",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
        )
        self.queue = sqs.Queue(
            self,
            "Work",
            queue_name=f"{PREFIX}-work",
            retention_period=Duration.days(4),
            visibility_timeout=Duration.minutes(5),
            receive_message_wait_time=Duration.seconds(20),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=8, queue=self.dlq),
        )

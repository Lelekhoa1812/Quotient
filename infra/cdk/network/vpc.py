# Motivation vs Logic
# Motivation: Place Quotient in its own Sydney VPC so staging traffic cannot
# land in an Engine subnet.
# Logic: Allocate 10.40.0.0/16 as two public /24s and two private /24s across
# two AZs. One NAT in the first public subnet. An S3 gateway endpoint on the
# private route tables so object transfer does not hairpin through the NAT.
# The endpoint policy stays open because Fargate pulls ECR layers from
# AWS-owned S3 buckets through the same gateway. Task IAM, not the endpoint,
# limits which application buckets credentials can use.

from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from quotient.names import PREFIX, VPC_CIDR


class MeetingVpc(Construct):
    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            vpc_name=PREFIX,
            ip_addresses=ec2.IpAddresses.cidr(VPC_CIDR),
            max_azs=2,
            nat_gateways=1,
            restrict_default_security_group=True,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )
        self.vpc.add_gateway_endpoint(
            "S3",
            service=ec2.GatewayVpcEndpointAwsService.S3,
            subnets=[ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)],
        )

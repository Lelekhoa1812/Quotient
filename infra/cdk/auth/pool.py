# Motivation vs Logic
# Motivation: Cognito is the OAuth 2.1 authorization server for the Quotient
# MCP resource. Partner material stays in Secrets Manager, not DynamoDB.
# Logic: A confidential-free public client uses the authorization-code grant,
# which forces PKCE for clients without a secret. The resource server scope
# is quotient/mcp. The RFC 8707 resource indicator is the MCP URL on the ALB,
# passed to the task as MCP_RESOURCE_URL by the compute construct. Hosted UI
# domain prefix is the staging prefix. Callback is localhost because this
# pass has no ACM hostname.

from aws_cdk import Duration, RemovalPolicy, aws_cognito as cognito, aws_secretsmanager as secretsmanager
from constructs import Construct

from quotient.names import PORTAL_ORIGIN, PREFIX


class MeetingAuth(Construct):
    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)
        self.scope_name = "mcp"
        self.resource_id = "quotient"
        self.pool = cognito.UserPool(
            self,
            "Users",
            user_pool_name=PREFIX,
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN,
        )
        scope_def = cognito.ResourceServerScope(
            scope_name=self.scope_name,
            scope_description="Call the Quotient MCP resource",
        )
        self.resource_server = self.pool.add_resource_server(
            "Mcp",
            identifier=self.resource_id,
            scopes=[scope_def],
        )
        self.client = self.pool.add_client(
            "Portal",
            user_pool_client_name=f"{PREFIX}-portal",
            generate_secret=False,
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
            auth_flows=cognito.AuthFlow(user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.resource_server(self.resource_server, scope_def),
                ],
                callback_urls=[f"{PORTAL_ORIGIN}/callback"],
                logout_urls=[f"{PORTAL_ORIGIN}/"],
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
        )
        self.domain = self.pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=PREFIX),
        )
        self.partner_secret = secretsmanager.Secret(
            self,
            "Partner",
            secret_name=f"{PREFIX}/partner",
            description="Partner OAuth material for Quotient staging. Not stored in DynamoDB.",
            removal_policy=RemovalPolicy.RETAIN,
        )

    @property
    def oauth_scope(self) -> str:
        return f"{self.resource_id}/{self.scope_name}"

# Motivation vs Logic
# Motivation: Keep the staging identity in one module so resource names, model
# allow-lists, and the VPC CIDR cannot drift between constructs.
# Logic: Constants only. Engine CIDRs are not defined here, so no construct can
# import or peer those networks by referencing this module.

PREFIX = "axion-meeting-staging"
ACCOUNT = "255834078973"
REGION = "ap-southeast-2"
# 10.40.0.0/16 is kollab-staging-vpc in this account. 10.50.0.0/16 is free
# and is not peered with the Engine VPCs (10.20.0.0/16, 10.30.0.0/16).
VPC_CIDR = "10.50.0.0/16"

SONIC_MODEL_ID = "amazon.nova-2-5-sonic"
SONIC_REGION = "ap-northeast-1"

# Global and regional inference profiles invoked from Sydney. The fallback id
# is the global Haiku profile used when the au profile is not invocable.
PEGASUS_PROFILE = "global.twelvelabs.pegasus-1-5-v1:0"
LLM_PROFILE = "au.anthropic.claude-haiku-5-5"
SLM_PROFILE = "au.anthropic.claude-haiku-5-5"
LLM_FALLBACK_PROFILE = "global.anthropic.claude-haiku-5-5"

GLOBAL_PROFILES = (
    PEGASUS_PROFILE,
    LLM_PROFILE,
    LLM_FALLBACK_PROFILE,
)

# Foundation models behind those profiles. Sonic is intentionally absent.
# Sol and Luna share the Haiku foundation model.
GLOBAL_FOUNDATION_MODELS = (
    "twelvelabs.pegasus-1-5-v1:0",
    "anthropic.claude-haiku-5-5",
)

# Coarse DAG stage ids. Council entries are the ten blinded dimensions.
COUNCIL_STAGES = (
    "decision",
    "commitment",
    "temporal",
    "stakeholder",
    "cross_modal",
    "documentary",
    "risk",
    "gap",
    "dependency",
    "question",
)

IMAGE_TAG = "staging"
DERIVATIVES_PREFIX = "derivatives/"
SANDBOX_PREFIX = "sandbox/"
API_PORT = 8080
WEB_PORT = 3000
PORTAL_ORIGIN = "http://localhost:3000"


def tokyo_sonic_arn() -> str:
    return f"arn:aws:bedrock:{SONIC_REGION}::foundation-model/{SONIC_MODEL_ID}"


def sydney_profile_arns() -> list[str]:
    return [
        f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/{profile_id}"
        for profile_id in GLOBAL_PROFILES
    ]


def global_foundation_arns() -> list[str]:
    return [
        f"arn:aws:bedrock:*::foundation-model/{model_id}"
        for model_id in GLOBAL_FOUNDATION_MODELS
    ]


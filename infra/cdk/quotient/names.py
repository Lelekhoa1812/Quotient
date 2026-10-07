# Motivation vs Logic
# Motivation: Keep the staging identity in one module so resource names, model
# allow-lists, and the VPC CIDR cannot drift between constructs.
# Logic: Constants only. Engine CIDRs are not defined here, so no construct can
# import or peer those networks by referencing this module.

PREFIX = "axion-meeting-staging"
ACCOUNT = "255834078973"
REGION = "ap-southeast-2"
VPC_CIDR = "10.40.0.0/16"

SONIC_MODEL_ID = "amazon.nova-2-5-sonic"
SONIC_REGION = "ap-northeast-1"

# Global inference profiles invoked from Sydney. The fallback id is the
# pre-6.1 Sol profile used when gpt-6.1-sol is not invocable.
GLOBAL_PROFILES = (
    "global.twelvelabs.pegasus-1-2-v1:0",
    "global.openai.gpt-6.1-sol",
    "global.openai.gpt-6-luna",
    "global.openai.gpt-6-sol",
)

# Foundation models behind those profiles. Sonic is intentionally absent.
GLOBAL_FOUNDATION_MODELS = (
    "twelvelabs.pegasus-1-2-v1:0",
    "openai.gpt-6.1-sol",
    "openai.gpt-6-luna",
    "openai.gpt-6-sol",
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

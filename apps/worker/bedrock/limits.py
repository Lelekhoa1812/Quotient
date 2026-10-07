# Motivation vs Logic
# Motivation: Product spend stops must not shrink model output below the vendor maximum.
# Logic: These constants are the card maxima. Call sites send them verbatim and reject any lower value.

SONIC_MODEL = "amazon.nova-2-5-sonic"
SONIC_REGION = "ap-northeast-1"
SONIC_SAMPLE_RATE = 16000
SONIC_FRAME_SAMPLES = 512
SONIC_FRAME_SECONDS = 0.032
SONIC_HANDOFF_SAMPLES = 6 * 60 * SONIC_SAMPLE_RATE

PEGASUS_MODEL = "global.twelvelabs.pegasus-1-2-v1:0"
PEGASUS_REGION = "ap-southeast-2"
PEGASUS_MAX_OUTPUT_TOKENS = 4096
PEGASUS_BUCKET_OWNER = "255834078973"
PEGASUS_PART_MAX_MS = 50 * 60 * 1000

SOL_MODEL = "global.openai.gpt-6.1-sol"
SOL_FALLBACK = "global.openai.gpt-6-sol"
SOL_MAX_OUTPUT_TOKENS = 131072
LUNA_MODEL = "global.openai.gpt-6-luna"
LUNA_MAX_OUTPUT_TOKENS = 128000
REASON_REGION = "ap-southeast-2"
INPUT_TOKEN_BUDGET = 272_000

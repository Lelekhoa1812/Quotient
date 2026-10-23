# Motivation vs Logic
# Motivation: Each model stays inside the vendor card for that model.
# Logic: Sol and Luna send their card maxima. Pegasus scales with the window and stops at 98304.

SONIC_MODEL = "amazon.nova-2-5-sonic"
SONIC_REGION = "ap-northeast-1"
SONIC_SAMPLE_RATE = 16000
SONIC_FRAME_SAMPLES = 512
SONIC_FRAME_SECONDS = 0.032
SONIC_HANDOFF_SAMPLES = 6 * 60 * SONIC_SAMPLE_RATE

PEGASUS_MODEL = "global.twelvelabs.pegasus-1-5-v1:0"
PEGASUS_REGION = "ap-southeast-2"
# Pegasus 1.5 vendor card. A call below the floor is rejected. A call above the ceiling is rejected.
PEGASUS_MIN_OUTPUT_TOKENS = 512
PEGASUS_MAX_OUTPUT_TOKENS = 98304
# Pegasus 1.2 spent its whole 4096-token card on a 3 minute window. Keep that many tokens per minute.
PEGASUS_DENSITY_TOKENS = 4096
PEGASUS_DENSITY_WINDOW_MS = 3 * 60 * 1000
PEGASUS_BUCKET_OWNER = "255834078973"
# One window fills the 98304 card at the 1.2 density: 98304 / 4096 * 3 minutes = 72 minutes.
# The vendor accepts 2 hours of video. A longer window would thin the same card.
PEGASUS_WINDOW_MS = PEGASUS_MAX_OUTPUT_TOKENS * PEGASUS_DENSITY_WINDOW_MS // PEGASUS_DENSITY_TOKENS
PEGASUS_WINDOW_MIN_TAIL_MS = 45 * 1000
# A short tail may join the previous window. The joined part can pass the card, and the token
# function then clamps to PEGASUS_MAX_OUTPUT_TOKENS.
PEGASUS_PART_MAX_MS = PEGASUS_WINDOW_MS + PEGASUS_WINDOW_MIN_TAIL_MS


def pegasus_output_tokens(duration_ms: int) -> int:
    """Tokens for one window. Short windows use the vendor floor. Long windows stop at the vendor ceiling."""
    if duration_ms <= 0:
        return PEGASUS_MIN_OUTPUT_TOKENS
    raw = (duration_ms * PEGASUS_DENSITY_TOKENS + PEGASUS_DENSITY_WINDOW_MS - 1) // PEGASUS_DENSITY_WINDOW_MS
    return min(PEGASUS_MAX_OUTPUT_TOKENS, max(PEGASUS_MIN_OUTPUT_TOKENS, raw))

HAIKU_MODEL = "au.anthropic.claude-haiku-5-5"
HAIKU_FALLBACK = "global.anthropic.claude-haiku-5-5"
HAIKU_MAX_OUTPUT_TOKENS = 128000

# Haiku 5.5 is pinned for both LLM and SLM roles (with adaptive thinking effort)
SOL_MODEL = HAIKU_MODEL
SOL_FALLBACK = HAIKU_FALLBACK
SOL_MAX_OUTPUT_TOKENS = HAIKU_MAX_OUTPUT_TOKENS
LUNA_MODEL = HAIKU_MODEL
LUNA_MAX_OUTPUT_TOKENS = HAIKU_MAX_OUTPUT_TOKENS
REASON_REGION = "ap-southeast-2"
INPUT_TOKEN_BUDGET = 272_000

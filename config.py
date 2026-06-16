"""
config.py — Edit this file before running the bot.
"""

class Config:
    # ── Core ──────────────────────────────────────────
    TOKEN       = ""
    PREFIX      = "~"
    OWNER_IDS   = [1077905352244338688]

    # ── AI (Free forever) ─────────────────────────────
    GROQ_API_KEY = ""

    # ── Cookie API (for transcripts) ──────────────────
    # Get free key at: https://cookie-api.com
    COOKIE_API_KEY = ""

    # ── Colors ────────────────────────────────────────
    COLOR_OK    = 0x2ECC71
    COLOR_ERR   = 0xE74C3C
    COLOR_WARN  = 0xF39C12
    COLOR_INFO  = 0x3498DB
    COLOR_MOD   = 0x9B59B6
    COLOR_GOLD  = 0xF1C40F

    # ── Economy ───────────────────────────────────────
    DAILY_AMOUNT        = 200
    WORK_MIN            = 50
    WORK_MAX            = 300
    STARTING_BALANCE    = 500
    CURRENCY_EMOJI      = "💰"
    CURRENCY_NAME       = "coins"

    # ── Leveling ──────────────────────────────────────
    XP_PER_MESSAGE_MIN  = 10
    XP_PER_MESSAGE_MAX  = 25
    XP_COOLDOWN_SECONDS = 60

    # ── Auto-Mod ──────────────────────────────────────
    SPAM_MESSAGE_COUNT  = 5
    SPAM_INTERVAL       = 5
    SPAM_MUTE_DURATION  = 300
    MAX_MENTIONS        = 5
    MAX_CAPS_PERCENT    = 70
    BAD_WORDS           = ["fuck", "nigger", "ass", "lesbian", "murder", "kill"]

    # ── Music ─────────────────────────────────────────
    MAX_QUEUE_LENGTH    = 100
    DEFAULT_VOLUME      = 100

    # ── Tickets ───────────────────────────────────────
    TICKET_CATEGORY_NAME = "Tickets"
    TICKET_LOG_CHANNEL   = 1501393214953885837

    # ── Giveaways ─────────────────────────────────────
    GIVEAWAY_EMOJI  = "🎉"

    # ── Data ──────────────────────────────────────────
    DATA_DIR = "data"

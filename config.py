# =============================================================================
# config.py — Stock & Crypto Screener Pro
# Central configuration for all settings, API keys, and constants
# =============================================================================

import os

# =============================================================================
# API KEYS
# Get your FREE Alpha Vantage key at: https://alphavantage.co/support/#api-key
# Then replace the string below or set the environment variable:
#   export ALPHA_VANTAGE_KEY="your_key_here"
# =============================================================================

ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "YOUR_KEY_HERE")

# CoinGecko — No key needed (free public API)
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

# Alpha Vantage base URL
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"

# =============================================================================
# SCREENING FILTERS
# =============================================================================

STOCK_MAX_PRICE = 20.00          # Only show stocks at or below this price
CRYPTO_MAX_PRICE = 20.00         # Only show cryptos at or below this price
TOP_N_STOCKS = 5                 # Number of top stocks to display daily
TOP_N_CRYPTOS = 5                # Number of top cryptos to display daily

# Minimum liquidity requirements (avoids penny stock traps)
STOCK_MIN_VOLUME = 100_000       # Minimum average daily volume
STOCK_MIN_DOLLAR_VOLUME = 100_000  # Minimum daily dollar volume
CRYPTO_MIN_VOLUME_24H = 100_000  # Minimum 24h crypto volume in USD

# =============================================================================
# STOCK SIGNAL WEIGHTS (must sum to 1.0)
# Ranked by user priority: RVOL > Momentum > VWAP > Breakout > ATR >
#                          RSI > ADX > Gap > Liquidity > Catalyst
# =============================================================================

STOCK_SIGNAL_WEIGHTS = {
    "rvol":      0.30,   # Relative Volume
    "momentum":  0.25,   # % Price Change + Multi-Timeframe Trend
    "vwap":      0.20,   # VWAP Position / Reclaim
    "breakout":  0.15,   # Breakout Above Resistance (HOD / Range Break)
    "atr":       0.10,   # ATR Expansion (Volatility Spike)
}

assert abs(sum(STOCK_SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9, \
    "Stock signal weights must sum to 1.0"

# =============================================================================
# CRYPTO SIGNAL WEIGHTS (must sum to 1.0)
# Ranked by user priority: Volume Spike > Momentum > Breakout > Volatility > Liquidity
# =============================================================================

CRYPTO_SIGNAL_WEIGHTS = {
    "volume_spike": 0.30,  # 24h volume vs 7-day average
    "momentum":     0.25,  # 1h and 24h price changes
    "breakout":     0.20,  # Position vs 7-day and 30-day range
    "volatility":   0.15,  # 24h volatility vs baseline
    "liquidity":    0.10,  # Spread quality + volume depth
}

assert abs(sum(CRYPTO_SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9, \
    "Crypto signal weights must sum to 1.0"

# =============================================================================
# SIGNAL SCORING THRESHOLDS — Stocks
# =============================================================================

# RVOL: score rises with relative volume vs average
RVOL_THRESHOLDS = {
    "exceptional": 5.0,   # Score 10 — 5x normal volume
    "very_high":   3.0,   # Score 8
    "high":        2.0,   # Score 6
    "moderate":    1.5,   # Score 4
    "low":         1.0,   # Score 2
}

# RSI scoring bands
RSI_BULLISH_MIN = 55    # Healthy momentum starts here
RSI_BULLISH_MAX = 75    # Above 75 = overbought risk, score decreases
RSI_OVERSOLD    = 30    # Below 30 = potential reversal zone
RSI_OVERBOUGHT  = 80    # Above 80 = heavy overbought penalty

# ADX: trend strength
ADX_STRONG_TREND  = 40  # Score 10
ADX_GOOD_TREND    = 25  # Score 7
ADX_WEAK_TREND    = 15  # Score 4
ADX_NO_TREND      = 10  # Score 1

# Gap strength thresholds (% gap from prior close)
GAP_EXCEPTIONAL = 10.0  # +10% gap = score 10
GAP_STRONG      = 5.0   # +5%  gap = score 8
GAP_MODERATE    = 2.0   # +2%  gap = score 5
GAP_FLAT        = 0.5   # < 0.5% = score 1

# ATR expansion: ratio of current ATR vs 20-day baseline
ATR_SPIKE_HIGH   = 2.0  # 2x baseline = score 10
ATR_SPIKE_MED    = 1.5  # 1.5x = score 7
ATR_SPIKE_LOW    = 1.2  # 1.2x = score 4
ATR_BASELINE     = 1.0  # At baseline = score 2

# =============================================================================
# SIGNAL SCORING THRESHOLDS — Crypto
# =============================================================================

# Volume spike: ratio of 24h volume vs 7-day average
CRYPTO_VOL_SPIKE_HIGH = 3.0   # Score 10
CRYPTO_VOL_SPIKE_MED  = 2.0   # Score 7
CRYPTO_VOL_SPIKE_LOW  = 1.5   # Score 4

# Crypto momentum (24h % change)
CRYPTO_MOM_STRONG  = 10.0   # +10% = score 10
CRYPTO_MOM_GOOD    = 5.0    # +5%  = score 7
CRYPTO_MOM_MILD    = 2.0    # +2%  = score 4
CRYPTO_MOM_FLAT    = 0.0    # 0%   = score 1

# =============================================================================
# PAPER TRADING SETTINGS
# =============================================================================

PAPER_STOCK_BALANCE  = 500.00   # Starting balance for stock paper account ($)
PAPER_CRYPTO_BALANCE = 15.00    # Starting balance for crypto paper account ($)
SLIPPAGE_RATE        = 0.001    # 0.1% slippage on all fills
PARTIAL_FILL_CHANCE  = 0.15     # 15% chance of partial fill on limit orders
PARTIAL_FILL_MIN_PCT = 0.50     # Partial fills between 50%–99% of order size
PARTIAL_FILL_MAX_PCT = 0.99

# Trailing stop default offset (% from high-water mark)
DEFAULT_TRAILING_STOP_PCT = 0.05  # 5%

# =============================================================================
# DASHBOARD / UI SETTINGS
# =============================================================================

AUTO_REFRESH_INTERVAL_MINUTES = 5   # How often the dashboard auto-refreshes
MAX_WATCHLIST_SIZE = 20              # Max tickers a user can save to watchlist
PRICE_ALERT_CHECK_INTERVAL_SEC = 30 # How often to check price alerts (seconds)

# =============================================================================
# DATA FETCHING SETTINGS
# =============================================================================

# Stock universe to scan (expanded small/mid cap under $20)
STOCK_SCAN_UNIVERSE = [
    # High-volume small caps frequently under $20
    "SNDL", "CLOV", "WISH", "EXPR", "BBIG", "FFIE", "MULN", "WKHS",
    "RIDE", "NKLA", "GOEV", "HYLN", "OPEN", "UWMC", "CANO", "PRTY",
    "SPCE", "ANY", "CENN", "ILUS", "ABEV", "NOK", "BB", "VALE",
    "ITUB", "PBR", "SID", "ERIC", "TELL", "GEVO", "AMTX", "REI",
    "PLUG", "FCEL", "BLNK", "CHPT", "SOLO", "KNDI", "ZEV", "NXTD",
    "SHIP", "TOPS", "GLBS", "EDRY", "FREE", "TBLT", "BOXL", "MVIS",
    "XELA", "IDEX", "ATER", "SPRT", "MEGL", "IMPP", "INPX", "KALI",
    "PHUN", "VERB", "AMC", "GME", "SIRI", "NAKD", "CTRM", "JAGX",
    "GFAI", "MINE", "DPRO", "ABML", "CLPS", "HPNN", "ABUS", "AVGR",
    "AGRX", "AIKI", "BFRI", "BNGO", "BIVI", "CFRX", "CYCC", "DARE",
]

# CoinGecko crypto IDs to scan (under $20 coins by typical price range)
CRYPTO_SCAN_IDS = [
    "ripple", "cardano", "dogecoin", "shiba-inu", "tron",
    "stellar", "vechain", "the-open-network", "hedera-hashgraph",
    "algorand", "iota", "neo", "zilliqa", "waves", "holo",
    "ankr", "coti", "harmony", "wink", "truebit-protocol",
    "just", "sun-token", "klaytn", "casper-network", "dent",
    "fetch-ai", "ocean-protocol", "storj", "loopring", "band-protocol",
    "origintrail", "lto-network", "loom-network", "steem", "hive",
    "aelf", "wanchain", "ardor", "nxt", "syscoin",
]

# =============================================================================
# TIMEZONE
# =============================================================================

TIMEZONE = "America/New_York"   # All timestamps in US Eastern Time

# =============================================================================
# FILE PATHS
# =============================================================================

RESULTS_FILE    = "screening_results.json"
TRADES_CSV_FILE = "trades_export.csv"
DASHBOARD_FILE  = "dashboard.html"
PORTFOLIO_FILE  = "portfolio_state.json"

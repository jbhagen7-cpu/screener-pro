# =============================================================================
# market_screener.py — Stock & Crypto Screener Pro
# Signal calculation + composite scoring for stocks and cryptos
# =============================================================================

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import config as cfg
    SW = cfg.STOCK_SIGNAL_WEIGHTS
    CW = cfg.CRYPTO_SIGNAL_WEIGHTS
except ImportError:
    SW = dict(rvol=0.15, momentum=0.14, vwap=0.13, breakout=0.12,
              atr=0.11, rsi=0.10, adx=0.09, gap=0.08, liquidity=0.05, catalyst=0.03)
    CW = dict(volume_spike=0.30, momentum=0.25, breakout=0.20, volatility=0.15, liquidity=0.10)


# =============================================================================
# HELPERS
# =============================================================================

def clamp(val: float, lo=0.0, hi=10.0) -> float:
    return max(lo, min(hi, val))

def score_linear(val, low_val, high_val, low_score=0.0, high_score=10.0) -> float:
    """Linearly interpolate val between [low_val, high_val] → [low_score, high_score]."""
    if high_val == low_val:
        return low_score
    ratio = (val - low_val) / (high_val - low_val)
    return clamp(low_score + ratio * (high_score - low_score))


# =============================================================================
# STOCK SIGNALS  (each returns 0–10)
# =============================================================================

def score_rvol(data: dict) -> float:
    """Relative Volume vs 20-day average."""
    rvol = data.get('rvol', 1.0)
    if   rvol >= 5.0: return 10.0
    elif rvol >= 3.0: return score_linear(rvol, 3.0, 5.0, 8.0, 10.0)
    elif rvol >= 2.0: return score_linear(rvol, 2.0, 3.0, 6.0, 8.0)
    elif rvol >= 1.5: return score_linear(rvol, 1.5, 2.0, 4.0, 6.0)
    elif rvol >= 1.0: return score_linear(rvol, 1.0, 1.5, 2.0, 4.0)
    else:             return score_linear(rvol, 0.0, 1.0, 0.0, 2.0)


def score_momentum(data: dict) -> float:
    """% Price change today, weighted toward positive momentum."""
    chg = data.get('change_pct', 0.0)
    if   chg >= 15.0: return 10.0
    elif chg >= 10.0: return score_linear(chg, 10.0, 15.0, 8.5, 10.0)
    elif chg >=  5.0: return score_linear(chg,  5.0, 10.0, 6.5, 8.5)
    elif chg >=  2.0: return score_linear(chg,  2.0,  5.0, 4.5, 6.5)
    elif chg >=  0.5: return score_linear(chg,  0.5,  2.0, 3.0, 4.5)
    elif chg >= -1.0: return score_linear(chg, -1.0,  0.5, 1.5, 3.0)
    elif chg >= -5.0: return score_linear(chg, -5.0, -1.0, 0.0, 1.5)
    else:             return 0.0


def score_vwap(data: dict) -> float:
    """Price position vs VWAP — above VWAP = institutional support."""
    price = data.get('price', 0)
    vwap  = data.get('vwap', price)
    if vwap <= 0:
        return 5.0
    pct_diff = ((price - vwap) / vwap) * 100
    if   pct_diff >=  3.0: return 10.0
    elif pct_diff >=  1.0: return score_linear(pct_diff, 1.0, 3.0, 7.0, 10.0)
    elif pct_diff >=  0.0: return score_linear(pct_diff, 0.0, 1.0, 5.5, 7.0)
    elif pct_diff >= -1.0: return score_linear(pct_diff,-1.0, 0.0, 3.5, 5.5)
    elif pct_diff >= -3.0: return score_linear(pct_diff,-3.0,-1.0, 1.5, 3.5)
    else:                  return 0.0


def score_breakout(data: dict) -> float:
    """Breakout above 20-day high and proximity to 52-week high."""
    price    = data.get('price', 0)
    high_20d = data.get('high_20d', price)
    high_52w = data.get('high_52w', price)
    if high_20d <= 0 or high_52w <= 0:
        return 5.0

    # Distance from 20-day high (negative = above, positive = below)
    dist_20d = ((high_20d - price) / high_20d) * 100

    # Position within 52-week range
    low_52w  = data.get('low_52w', price * 0.5)
    rng      = high_52w - low_52w
    pos_52w  = ((price - low_52w) / rng * 100) if rng > 0 else 50

    # Score: reward breaking above 20d high, penalize far below
    if   dist_20d <= -2.0: breakout_score = 10.0  # Above 20d high
    elif dist_20d <=  0.0: breakout_score = score_linear(dist_20d, -2.0, 0.0, 8.0, 10.0)
    elif dist_20d <=  3.0: breakout_score = score_linear(dist_20d,  0.0, 3.0, 5.0, 8.0)
    elif dist_20d <= 10.0: breakout_score = score_linear(dist_20d,  3.0,10.0, 2.0, 5.0)
    else:                  breakout_score = 1.0

    # Bonus for high 52w position
    pos_bonus = pos_52w / 100 * 2  # up to +2 pts

    return clamp(breakout_score + pos_bonus)


def score_atr(data: dict) -> float:
    """ATR expansion — current ATR vs baseline (active mover signal)."""
    atr_14   = data.get('atr_14', 0)
    atr_base = data.get('atr_base', atr_14)
    if atr_base <= 0:
        return 5.0
    ratio = atr_14 / atr_base
    if   ratio >= 2.5: return 10.0
    elif ratio >= 2.0: return score_linear(ratio, 2.0, 2.5, 8.5, 10.0)
    elif ratio >= 1.5: return score_linear(ratio, 1.5, 2.0, 6.5, 8.5)
    elif ratio >= 1.2: return score_linear(ratio, 1.2, 1.5, 4.0, 6.5)
    elif ratio >= 1.0: return score_linear(ratio, 1.0, 1.2, 2.5, 4.0)
    else:              return score_linear(ratio, 0.5, 1.0, 0.0, 2.5)


def score_rsi(data: dict) -> float:
    """RSI: reward 55–75 (strong momentum), penalize extremes."""
    rsi = data.get('rsi', 50.0)
    if   55 <= rsi <= 70: return score_linear(rsi, 55, 70, 8.0, 10.0)
    elif 70 <  rsi <= 75: return score_linear(rsi, 70, 75, 8.0,  6.0)   # slight overbought
    elif 75 <  rsi <= 80: return score_linear(rsi, 75, 80, 6.0,  3.0)   # overbought
    elif rsi  > 80:       return 1.0                                      # extreme overbought
    elif 45 <= rsi <  55: return score_linear(rsi, 45, 55, 4.0,  8.0)
    elif 30 <= rsi <  45: return score_linear(rsi, 30, 45, 2.0,  4.0)
    elif rsi  < 30:       return score_linear(rsi, 20, 30, 3.0,  2.0)   # oversold bounce potential
    return 5.0


def score_adx(data: dict) -> float:
    """ADX trend strength — higher ADX = stronger directional trend."""
    adx = data.get('adx', 20.0)
    if   adx >= 40: return 10.0
    elif adx >= 30: return score_linear(adx, 30, 40, 7.5, 10.0)
    elif adx >= 25: return score_linear(adx, 25, 30, 6.0,  7.5)
    elif adx >= 20: return score_linear(adx, 20, 25, 4.0,  6.0)
    elif adx >= 15: return score_linear(adx, 15, 20, 2.0,  4.0)
    else:           return score_linear(adx,  5, 15, 0.0,  2.0)


def score_gap(data: dict) -> float:
    """Gap strength vs prior close — premarket interest signal."""
    gap = data.get('gap_pct', 0.0)
    if   gap >= 10.0: return 10.0
    elif gap >=  5.0: return score_linear(gap,  5.0, 10.0, 8.0, 10.0)
    elif gap >=  2.0: return score_linear(gap,  2.0,  5.0, 5.0,  8.0)
    elif gap >=  0.5: return score_linear(gap,  0.5,  2.0, 3.0,  5.0)
    elif gap >= -0.5: return 2.5
    elif gap >= -2.0: return score_linear(gap, -2.0, -0.5, 1.0,  2.5)
    else:             return 0.0


def score_liquidity(data: dict) -> float:
    """Liquidity quality: dollar volume + tight spread proxy."""
    dvol = data.get('dollar_volume', 0)
    vol  = data.get('volume', 0)
    avg  = data.get('avg_volume_20', 1)

    # Dollar volume score
    if   dvol >= 10_000_000: dv_score = 10.0
    elif dvol >=  5_000_000: dv_score = score_linear(dvol, 5e6, 10e6, 7.0, 10.0)
    elif dvol >=  2_000_000: dv_score = score_linear(dvol, 2e6,  5e6, 5.0,  7.0)
    elif dvol >=  1_000_000: dv_score = score_linear(dvol, 1e6,  2e6, 3.0,  5.0)
    elif dvol >=    500_000: dv_score = score_linear(dvol, 5e5,  1e6, 1.0,  3.0)
    else:                    dv_score = 0.0

    # Consistency bonus (volume vs 20-day average)
    cons = vol / avg if avg > 0 else 1.0
    bonus = min(cons * 0.5, 1.5)

    return clamp(dv_score + bonus)


def score_catalyst(data: dict) -> float:
    """News/catalyst presence — earnings within 7 days or flagged event."""
    has_earnings = data.get('has_earnings', False)
    # Future: integrate news API. For now use earnings flag.
    if has_earnings:
        return 8.0
    return 3.0   # Neutral — no confirmed catalyst


# =============================================================================
# CRYPTO SIGNALS  (each returns 0–10)
# =============================================================================

def score_crypto_volume_spike(data: dict) -> float:
    """24h volume vs 7-day average."""
    spike = data.get('vol_spike', 1.0)
    if   spike >= 5.0: return 10.0
    elif spike >= 3.0: return score_linear(spike, 3.0, 5.0, 8.0, 10.0)
    elif spike >= 2.0: return score_linear(spike, 2.0, 3.0, 6.0,  8.0)
    elif spike >= 1.5: return score_linear(spike, 1.5, 2.0, 4.0,  6.0)
    elif spike >= 1.0: return score_linear(spike, 1.0, 1.5, 2.0,  4.0)
    else:              return score_linear(spike, 0.0, 1.0, 0.0,  2.0)


def score_crypto_momentum(data: dict) -> float:
    """Combined 1h + 24h price change, weighted toward 24h."""
    chg_24h = data.get('change_24h', 0.0)
    chg_1h  = data.get('change_1h',  0.0)
    combined = chg_24h * 0.7 + chg_1h * 0.3

    if   combined >= 20.0: return 10.0
    elif combined >= 10.0: return score_linear(combined, 10.0, 20.0, 8.0, 10.0)
    elif combined >=  5.0: return score_linear(combined,  5.0, 10.0, 6.0,  8.0)
    elif combined >=  2.0: return score_linear(combined,  2.0,  5.0, 4.0,  6.0)
    elif combined >=  0.0: return score_linear(combined,  0.0,  2.0, 2.5,  4.0)
    elif combined >= -3.0: return score_linear(combined, -3.0,  0.0, 1.0,  2.5)
    else:                  return 0.0


def score_crypto_breakout(data: dict) -> float:
    """Position vs 7-day and 30-day ranges."""
    price    = data.get('price', 0)
    high_7d  = data.get('high_7d',  price)
    low_7d   = data.get('low_7d',   price)
    high_30d = data.get('high_30d', price)
    low_30d  = data.get('low_30d',  price)

    # Position in 7d range
    rng_7d  = high_7d  - low_7d
    pos_7d  = ((price - low_7d)  / rng_7d  * 100) if rng_7d  > 0 else 50

    # Position in 30d range
    rng_30d = high_30d - low_30d
    pos_30d = ((price - low_30d) / rng_30d * 100) if rng_30d > 0 else 50

    combined = pos_7d * 0.6 + pos_30d * 0.4
    return score_linear(combined, 0, 100, 0, 10)


def score_crypto_volatility(data: dict) -> float:
    """24h volatility spike vs 7-day baseline."""
    vol_24h  = data.get('volatility_24h', 0)
    baseline = data.get('vol_baseline', vol_24h)
    if baseline <= 0:
        return 5.0
    ratio = vol_24h / baseline
    if   ratio >= 3.0: return 10.0
    elif ratio >= 2.0: return score_linear(ratio, 2.0, 3.0, 7.5, 10.0)
    elif ratio >= 1.5: return score_linear(ratio, 1.5, 2.0, 5.5,  7.5)
    elif ratio >= 1.0: return score_linear(ratio, 1.0, 1.5, 3.5,  5.5)
    else:              return score_linear(ratio, 0.5, 1.0, 0.0,  3.5)


def score_crypto_liquidity(data: dict) -> float:
    """Volume depth + estimated spread quality."""
    vol    = data.get('volume_24h', 0)
    spread = data.get('spread_pct', 0.5)

    # Volume score
    if   vol >= 100_000_000: vol_score = 10.0
    elif vol >=  50_000_000: vol_score = score_linear(vol, 50e6, 100e6, 8.0, 10.0)
    elif vol >=  10_000_000: vol_score = score_linear(vol, 10e6,  50e6, 6.0,  8.0)
    elif vol >=   5_000_000: vol_score = score_linear(vol,  5e6,  10e6, 4.5,  6.0)
    elif vol >=   1_000_000: vol_score = score_linear(vol,  1e6,   5e6, 2.5,  4.5)
    else:                    vol_score = 0.0

    # Spread penalty
    spread_penalty = min(spread * 5, 3.0)

    return clamp(vol_score - spread_penalty)


# =============================================================================
# COMPOSITE SCORING
# =============================================================================

def score_stock(data: dict) -> dict:
    """Calculate 5 signals + composite score for a stock."""
    signals = {
        'rvol':      score_rvol(data),
        'momentum':  score_momentum(data),
        'vwap':      score_vwap(data),
        'breakout':  score_breakout(data),
        'atr':       score_atr(data),
    }

    composite = sum(signals[k] * SW.get(k, 0.2) for k in signals) * 10

    if   composite >= 80: signal = 'Strong Buy'
    elif composite >= 65: signal = 'Buy'
    elif composite >= 45: signal = 'Neutral'
    else:                 signal = 'Weak'

    return {
        **data,
        'signals':   {k: round(v, 1) for k, v in signals.items()},
        'score':     round(composite, 1),
        'signal':    signal,
    }


def score_crypto(data: dict) -> dict:
    """Calculate all 5 signals + composite score for a crypto."""
    signals = {
        'volume_spike': score_crypto_volume_spike(data),
        'momentum':     score_crypto_momentum(data),
        'breakout':     score_crypto_breakout(data),
        'volatility':   score_crypto_volatility(data),
        'liquidity':    score_crypto_liquidity(data),
    }

    composite = sum(signals[k] * CW.get(k, 0.2) for k in signals) * 10

    if   composite >= 80: signal = 'Strong Buy'
    elif composite >= 65: signal = 'Buy'
    elif composite >= 45: signal = 'Neutral'
    else:                 signal = 'Weak'

    return {
        **data,
        'signals':   {k: round(v, 1) for k, v in signals.items()},
        'score':     round(composite, 1),
        'signal':    signal,
    }


# =============================================================================
# SCREENER — rank and return top N
# =============================================================================

class MarketScreener:

    def screen_stocks(self, raw_data: list, top_n: int = 5) -> list:
        """Score all stocks, return top N ranked by composite score."""
        logger.info(f"Scoring {len(raw_data)} stocks…")
        scored = []
        for item in raw_data:
            try:
                scored.append(score_stock(item))
            except Exception as e:
                logger.warning(f"Scoring error for {item.get('symbol','?')}: {e}")

        scored.sort(key=lambda x: x['score'], reverse=True)
        top = scored[:top_n]

        # Add rank
        for i, s in enumerate(top):
            s['rank'] = i + 1

        logger.info(f"Top {top_n} stocks: {[s['symbol'] for s in top]}")
        return top

    def screen_cryptos(self, raw_data: list, top_n: int = 5) -> list:
        """Score all cryptos, return top N ranked by composite score."""
        logger.info(f"Scoring {len(raw_data)} cryptos…")
        scored = []
        for item in raw_data:
            try:
                scored.append(score_crypto(item))
            except Exception as e:
                logger.warning(f"Scoring error for {item.get('symbol','?')}: {e}")

        scored.sort(key=lambda x: x['score'], reverse=True)
        top = scored[:top_n]

        for i, s in enumerate(top):
            s['rank'] = i + 1

        logger.info(f"Top {top_n} cryptos: {[s['symbol'] for s in top]}")
        return top

# =============================================================================
# data_connector.py — Stock & Crypto Screener Pro
# Data fetching: yfinance (primary) → Alpha Vantage (fallback) + CoinGecko
# =============================================================================

import time
import logging
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Import config ──────────────────────────────────────────────────────────
try:
    import config as cfg
except ImportError:
    class cfg:
        ALPHA_VANTAGE_KEY       = "YOUR_KEY_HERE"
        ALPHA_VANTAGE_BASE_URL  = "https://www.alphavantage.co/query"
        COINGECKO_BASE_URL      = "https://api.coingecko.com/api/v3"
        COINGECKO_RATE_LIMIT    = 30
        DATA_STRATEGY           = "yfinance_first"
        STOCK_MAX_PRICE         = 20.0
        CRYPTO_MAX_PRICE        = 20.0
        STOCK_MIN_VOLUME        = 500_000
        STOCK_MIN_DOLLAR_VOLUME = 1_000_000
        CRYPTO_MIN_VOLUME_24H   = 500_000
        STOCK_SCAN_UNIVERSE     = []
        CRYPTO_SCAN_IDS         = []


# =============================================================================
# STOCK DATA
# =============================================================================

class StockConnector:
    """Fetches stock data via yfinance with Alpha Vantage fallback."""

    def __init__(self):
        self.av_key      = cfg.ALPHA_VANTAGE_KEY
        self.av_base     = cfg.ALPHA_VANTAGE_BASE_URL
        self.strategy    = getattr(cfg, 'DATA_STRATEGY', 'yfinance_first')
        self._av_calls   = 0
        self._av_reset   = time.time()

    # ── Rate limiter for Alpha Vantage (5 calls/min free tier) ──────────────
    def _av_rate_limit(self):
        now = time.time()
        if now - self._av_reset > 60:
            self._av_calls = 0
            self._av_reset = now
        if self._av_calls >= 5:
            sleep_for = 60 - (now - self._av_reset) + 1
            logger.info(f"AV rate limit — sleeping {sleep_for:.1f}s")
            time.sleep(max(sleep_for, 0))
            self._av_calls = 0
            self._av_reset = time.time()
        self._av_calls += 1

    # ── yfinance fetch ───────────────────────────────────────────────────────
    def fetch_yfinance(self, symbol: str) -> Optional[dict]:
        try:
            tk   = yf.Ticker(symbol)
            info = tk.info

            # Validate essential fields
            price = info.get('currentPrice') or info.get('regularMarketPrice')
            if not price:
                return None

            hist = tk.history(period='60d', interval='1d')
            if hist.empty or len(hist) < 10:
                return None

            hist_5m = tk.history(period='2d', interval='5m')

            close   = hist['Close']
            volume  = hist['Volume']
            high    = hist['High']
            low     = hist['Low']

            avg_vol_20 = volume.tail(20).mean()
            today_vol  = volume.iloc[-1]
            rvol       = today_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

            prev_close = close.iloc[-2] if len(close) > 1 else price
            change_pct = ((price - prev_close) / prev_close) * 100 if prev_close else 0

            # VWAP (intraday approximation)
            if not hist_5m.empty:
                tp   = (hist_5m['High'] + hist_5m['Low'] + hist_5m['Close']) / 3
                vwap = (tp * hist_5m['Volume']).sum() / hist_5m['Volume'].sum() \
                       if hist_5m['Volume'].sum() > 0 else price
            else:
                vwap = price

            # ATR (14-period)
            tr_list = []
            for i in range(1, min(15, len(hist))):
                tr = max(
                    high.iloc[-i] - low.iloc[-i],
                    abs(high.iloc[-i] - close.iloc[-i-1]),
                    abs(low.iloc[-i]  - close.iloc[-i-1])
                )
                tr_list.append(tr)
            atr_14   = sum(tr_list) / len(tr_list) if tr_list else 0
            atr_base = sum(tr_list[-5:]) / 5 if len(tr_list) >= 5 else atr_14

            # RSI (14)
            delta  = close.diff().dropna()
            gain   = delta.clip(lower=0).tail(14).mean()
            loss   = (-delta.clip(upper=0)).tail(14).mean()
            rs     = gain / loss if loss != 0 else 100
            rsi    = 100 - (100 / (1 + rs))

            # ADX (simplified)
            adx = self._calc_adx(high, low, close)

            # 52-week high/low
            high_52w = high.tail(252).max() if len(high) >= 252 else high.max()
            low_52w  = low.tail(252).min()  if len(low)  >= 252 else low.min()
            high_20d = high.tail(20).max()

            # Gap %
            open_price = info.get('regularMarketOpen') or price
            gap_pct    = ((open_price - prev_close) / prev_close) * 100 if prev_close else 0

            # Dollar volume
            dollar_vol = price * today_vol

            return {
                'symbol':        symbol,
                'price':         round(price, 4),
                'prev_close':    round(prev_close, 4),
                'change_pct':    round(change_pct, 2),
                'open':          round(open_price, 4),
                'gap_pct':       round(gap_pct, 2),
                'volume':        int(today_vol),
                'avg_volume_20': int(avg_vol_20),
                'rvol':          round(rvol, 2),
                'dollar_volume': round(dollar_vol, 0),
                'vwap':          round(vwap, 4),
                'atr_14':        round(atr_14, 4),
                'atr_base':      round(atr_base, 4),
                'rsi':           round(rsi, 1),
                'adx':           round(adx, 1),
                'high_52w':      round(high_52w, 4),
                'low_52w':       round(low_52w, 4),
                'high_20d':      round(high_20d, 4),
                'market_cap':    info.get('marketCap', 0),
                'name':          info.get('longName') or info.get('shortName') or symbol,
                'sector':        info.get('sector', ''),
                'has_earnings':  self._check_earnings(info),
                'source':        'yfinance',
            }
        except Exception as e:
            logger.warning(f"yfinance failed for {symbol}: {e}")
            return None

    def _calc_adx(self, high, low, close, period=14) -> float:
        try:
            if len(high) < period + 2:
                return 20.0
            tr_list, pdm_list, ndm_list = [], [], []
            for i in range(1, period + 1):
                h, l, pc = high.iloc[-i], low.iloc[-i], close.iloc[-i-1]
                tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
                pdm_list.append(max(high.iloc[-i] - high.iloc[-i-1], 0)
                                 if high.iloc[-i] - high.iloc[-i-1] >
                                    low.iloc[-i-1] - low.iloc[-i] else 0)
                ndm_list.append(max(low.iloc[-i-1] - low.iloc[-i], 0)
                                 if low.iloc[-i-1] - low.iloc[-i] >
                                    high.iloc[-i] - high.iloc[-i-1] else 0)
            atr  = sum(tr_list) / period
            if atr == 0:
                return 20.0
            pdi  = (sum(pdm_list) / period) / atr * 100
            ndi  = (sum(ndm_list) / period) / atr * 100
            dx   = abs(pdi - ndi) / (pdi + ndi) * 100 if (pdi + ndi) > 0 else 0
            return round(dx, 1)
        except Exception:
            return 20.0

    def _check_earnings(self, info) -> bool:
        try:
            cal = info.get('earningsTimestamp')
            if cal:
                et = datetime.fromtimestamp(cal)
                return abs((et - datetime.now()).days) <= 7
        except Exception:
            pass
        return False

    # ── Alpha Vantage fallback ───────────────────────────────────────────────
    def fetch_alpha_vantage(self, symbol: str) -> Optional[dict]:
        if self.av_key == "YOUR_KEY_HERE":
            return None
        try:
            self._av_rate_limit()
            # Global quote
            r = requests.get(self.av_base, params={
                'function': 'GLOBAL_QUOTE',
                'symbol':   symbol,
                'apikey':   self.av_key,
            }, timeout=10)
            q = r.json().get('Global Quote', {})
            if not q or '05. price' not in q:
                return None

            price      = float(q['05. price'])
            prev_close = float(q['08. previous close'])
            change_pct = float(q['10. change percent'].replace('%',''))
            volume     = int(q['06. volume'])
            open_p     = float(q['02. open'])
            gap_pct    = ((open_p - prev_close) / prev_close * 100) if prev_close else 0

            self._av_rate_limit()
            # Daily adjusted for ATR/RSI/ADX
            r2 = requests.get(self.av_base, params={
                'function':   'TIME_SERIES_DAILY_ADJUSTED',
                'symbol':     symbol,
                'outputsize': 'compact',
                'apikey':     self.av_key,
            }, timeout=10)
            ts = r2.json().get('Time Series (Daily)', {})
            if not ts:
                return None

            dates  = sorted(ts.keys(), reverse=True)[:60]
            closes = [float(ts[d]['4. close']) for d in dates]
            highs  = [float(ts[d]['2. high'])  for d in dates]
            lows   = [float(ts[d]['3. low'])   for d in dates]
            vols   = [float(ts[d]['6. volume'])for d in dates]

            avg_vol_20 = sum(vols[:20]) / 20
            rvol       = volume / avg_vol_20 if avg_vol_20 > 0 else 1.0

            # ATR
            tr_list = [max(highs[i]-lows[i], abs(highs[i]-closes[i+1]),
                           abs(lows[i]-closes[i+1])) for i in range(14)]
            atr_14   = sum(tr_list) / 14
            atr_base = sum(tr_list[:5]) / 5

            # RSI
            deltas = [closes[i] - closes[i+1] for i in range(14)]
            gains  = [d for d in deltas if d > 0]
            losses = [-d for d in deltas if d < 0]
            avg_g  = sum(gains) / 14
            avg_l  = sum(losses) / 14
            rs     = avg_g / avg_l if avg_l > 0 else 100
            rsi    = 100 - 100/(1+rs)

            high_20d = max(highs[:20])
            high_52w = max(highs[:252] if len(highs)>=252 else highs)
            low_52w  = min(lows[:252]  if len(lows) >=252 else lows)

            return {
                'symbol':        symbol,
                'price':         round(price, 4),
                'prev_close':    round(prev_close, 4),
                'change_pct':    round(change_pct, 2),
                'open':          round(open_p, 4),
                'gap_pct':       round(gap_pct, 2),
                'volume':        volume,
                'avg_volume_20': int(avg_vol_20),
                'rvol':          round(rvol, 2),
                'dollar_volume': round(price * volume, 0),
                'vwap':          round(price, 4),   # AV doesn't give intraday VWAP
                'atr_14':        round(atr_14, 4),
                'atr_base':      round(atr_base, 4),
                'rsi':           round(rsi, 1),
                'adx':           20.0,              # Simplified
                'high_52w':      round(high_52w, 4),
                'low_52w':       round(low_52w, 4),
                'high_20d':      round(high_20d, 4),
                'market_cap':    0,
                'name':          symbol,
                'sector':        '',
                'has_earnings':  False,
                'source':        'alpha_vantage',
            }
        except Exception as e:
            logger.warning(f"Alpha Vantage failed for {symbol}: {e}")
            return None

    # ── Smart fetch with fallback ────────────────────────────────────────────
    def fetch(self, symbol: str) -> Optional[dict]:
        strategy = self.strategy
        if strategy == 'yfinance_first':
            data = self.fetch_yfinance(symbol)
            if not data:
                data = self.fetch_alpha_vantage(symbol)
        elif strategy == 'av_first':
            data = self.fetch_alpha_vantage(symbol)
            if not data:
                data = self.fetch_yfinance(symbol)
        elif strategy == 'av_only':
            data = self.fetch_alpha_vantage(symbol)
        else:
            data = self.fetch_yfinance(symbol)
        return data

    # ── Scan full universe ───────────────────────────────────────────────────
    def scan_universe(self) -> list:
        universe = cfg.STOCK_SCAN_UNIVERSE
        results  = []
        logger.info(f"Scanning {len(universe)} stocks…")
        for i, sym in enumerate(universe):
            try:
                data = self.fetch(sym)
                if not data:
                    continue
                # Price filter
                if data['price'] > cfg.STOCK_MAX_PRICE or data['price'] <= 0:
                    continue
                # Liquidity filters
                if data['volume'] < cfg.STOCK_MIN_VOLUME:
                    continue
                if data['dollar_volume'] < cfg.STOCK_MIN_DOLLAR_VOLUME:
                    continue
                results.append(data)
                logger.debug(f"  ✓ {sym} ${data['price']} RVOL={data['rvol']}")
            except Exception as e:
                logger.warning(f"Error scanning {sym}: {e}")
            # Small delay to respect rate limits
            if i % 10 == 9:
                time.sleep(1)
        logger.info(f"Stock scan complete: {len(results)} passed filters")
        return results


# =============================================================================
# CRYPTO DATA
# =============================================================================

class CryptoConnector:
    """Fetches crypto data from CoinGecko (free, no key needed)."""

    def __init__(self):
        self.base     = cfg.COINGECKO_BASE_URL
        self.rate_lim = getattr(cfg, 'COINGECKO_RATE_LIMIT', 30)
        self._last_call = 0

    def _rate_limit(self):
        min_gap = 60 / self.rate_lim
        elapsed = time.time() - self._last_call
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)
        self._last_call = time.time()

    def fetch_markets(self, ids: list) -> list:
        """Batch fetch market data for list of CoinGecko IDs."""
        try:
            self._rate_limit()
            r = requests.get(
                f"{self.base}/coins/markets",
                params={
                    'vs_currency':            'usd',
                    'ids':                    ','.join(ids),
                    'order':                  'volume_desc',
                    'per_page':               250,
                    'page':                   1,
                    'sparkline':              False,
                    'price_change_percentage':'1h,24h,7d',
                },
                timeout=15,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"CoinGecko markets fetch failed: {e}")
            return []

    def fetch_coin_detail(self, coin_id: str) -> Optional[dict]:
        """Fetch detailed data for a single coin (7d history for breakout calc)."""
        try:
            self._rate_limit()
            r = requests.get(
                f"{self.base}/coins/{coin_id}/market_chart",
                params={'vs_currency':'usd', 'days':'30', 'interval':'daily'},
                timeout=15,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"CoinGecko detail failed for {coin_id}: {e}")
            return None

    def scan_universe(self) -> list:
        """Scan crypto universe, enrich with historical data."""
        ids      = cfg.CRYPTO_SCAN_IDS
        results  = []
        logger.info(f"Scanning {len(ids)} cryptos…")

        # Batch fetch in groups of 50
        batch_size = 50
        market_data = []
        for i in range(0, len(ids), batch_size):
            batch = ids[i:i+batch_size]
            market_data.extend(self.fetch_markets(batch))
            time.sleep(2)

        for coin in market_data:
            try:
                price = coin.get('current_price', 0)
                if not price or price > cfg.CRYPTO_MAX_PRICE or price <= 0:
                    continue
                vol_24h = coin.get('total_volume', 0)
                if vol_24h < cfg.CRYPTO_MIN_VOLUME_24H:
                    continue

                # Historical data for 7d/30d range
                hist    = self.fetch_coin_detail(coin['id'])
                prices7 = []
                prices30= []
                vols7   = []
                if hist:
                    all_prices = [p[1] for p in hist.get('prices', [])]
                    all_vols   = [v[1] for v in hist.get('total_volumes', [])]
                    prices30   = all_prices
                    prices7    = all_prices[-7:]  if len(all_prices) >= 7  else all_prices
                    vols7      = all_vols[-7:]    if len(all_vols)   >= 7  else all_vols

                high_7d  = max(prices7)  if prices7  else price
                low_7d   = min(prices7)  if prices7  else price
                high_30d = max(prices30) if prices30 else price
                low_30d  = min(prices30) if prices30 else price

                avg_vol_7d = sum(vols7) / len(vols7) if vols7 else vol_24h
                vol_spike  = vol_24h / avg_vol_7d if avg_vol_7d > 0 else 1.0

                # 24h volatility
                if len(prices7) >= 2:
                    daily_rets = [abs(prices7[i]/prices7[i-1]-1)
                                  for i in range(1, len(prices7))]
                    volatility_24h = daily_rets[-1] if daily_rets else 0
                    vol_baseline   = sum(daily_rets) / len(daily_rets) if daily_rets else 0
                else:
                    volatility_24h = 0
                    vol_baseline   = 0

                results.append({
                    'id':              coin['id'],
                    'symbol':          coin['symbol'].upper(),
                    'name':            coin['name'],
                    'price':           round(price, 6),
                    'change_24h':      round(coin.get('price_change_percentage_24h', 0) or 0, 2),
                    'change_1h':       round(coin.get('price_change_percentage_1h_in_currency', 0) or 0, 2),
                    'change_7d':       round(coin.get('price_change_percentage_7d_in_currency', 0) or 0, 2),
                    'volume_24h':      round(vol_24h, 0),
                    'avg_vol_7d':      round(avg_vol_7d, 0),
                    'vol_spike':       round(vol_spike, 2),
                    'high_7d':         round(high_7d, 6),
                    'low_7d':          round(low_7d, 6),
                    'high_30d':        round(high_30d, 6),
                    'low_30d':         round(low_30d, 6),
                    'volatility_24h':  round(volatility_24h, 4),
                    'vol_baseline':    round(vol_baseline, 4),
                    'market_cap':      coin.get('market_cap', 0),
                    'market_cap_rank': coin.get('market_cap_rank', 999),
                    'spread_pct':      self._estimate_spread(vol_24h),
                    'source':          'coingecko',
                })
            except Exception as e:
                logger.warning(f"Error processing {coin.get('id','?')}: {e}")

        logger.info(f"Crypto scan complete: {len(results)} passed filters")
        return results

    def _estimate_spread(self, vol_24h: float) -> float:
        """Estimate bid-ask spread % from volume (lower volume = wider spread)."""
        if vol_24h > 100_000_000: return 0.05
        if vol_24h > 10_000_000:  return 0.10
        if vol_24h > 1_000_000:   return 0.20
        return 0.50


# =============================================================================
# CONVENIENCE WRAPPER
# =============================================================================

class DataConnector:
    def __init__(self):
        self.stocks  = StockConnector()
        self.cryptos = CryptoConnector()

    def scan_all(self) -> dict:
        logger.info("=== Starting full market scan ===")
        stock_data  = self.stocks.scan_universe()
        crypto_data = self.cryptos.scan_universe()
        return {'stocks': stock_data, 'cryptos': crypto_data}

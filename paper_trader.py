# =============================================================================
# paper_trader.py — Stock & Crypto Screener Pro
# Full paper trading engine: stop-loss, take-profit, trailing stop,
# partial fills, slippage, equity chart, CSV export
# =============================================================================

import csv
import json
import logging
import random
from copy import deepcopy
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import config as cfg
    STOCK_BAL      = cfg.PAPER_STOCK_BALANCE
    CRYPTO_BAL     = cfg.PAPER_CRYPTO_BALANCE
    SLIPPAGE       = cfg.SLIPPAGE_RATE
    PARTIAL_CHANCE = cfg.PARTIAL_FILL_CHANCE
    PARTIAL_MIN    = cfg.PARTIAL_FILL_MIN_PCT
    PARTIAL_MAX    = cfg.PARTIAL_FILL_MAX_PCT
    TRAIL_PCT      = cfg.DEFAULT_TRAILING_STOP_PCT
    TRADES_FILE    = cfg.TRADES_CSV_FILE
    PORTFOLIO_FILE = cfg.PORTFOLIO_FILE
except ImportError:
    STOCK_BAL      = 500.0
    CRYPTO_BAL     = 15.0
    SLIPPAGE       = 0.001
    PARTIAL_CHANCE = 0.15
    PARTIAL_MIN    = 0.50
    PARTIAL_MAX    = 0.99
    TRAIL_PCT      = 0.05
    TRADES_FILE    = "trades_export.csv"
    PORTFOLIO_FILE = "portfolio_state.json"


# =============================================================================
# ORDER TYPES
# =============================================================================

class OrderType:
    MARKET = 'market'
    LIMIT  = 'limit'

class OrderSide:
    BUY  = 'buy'
    SELL = 'sell'


# =============================================================================
# ACCOUNT
# =============================================================================

class Account:
    def __init__(self, name: str, starting_balance: float):
        self.name             = name
        self.cash             = starting_balance
        self.starting_balance = starting_balance
        self.positions        = {}   # symbol → Position
        self.trade_history    = []   # list of closed Trade dicts
        self.equity_curve     = [{'time': _now(), 'equity': starting_balance}]
        self.order_counter    = 0

    @property
    def total_equity(self) -> float:
        pos_value = sum(p.current_value for p in self.positions.values())
        return round(self.cash + pos_value, 4)

    @property
    def total_pnl(self) -> float:
        return round(self.total_equity - self.starting_balance, 4)

    @property
    def total_pnl_pct(self) -> float:
        return round((self.total_pnl / self.starting_balance) * 100, 2)

    def snapshot_equity(self):
        self.equity_curve.append({'time': _now(), 'equity': self.total_equity})

    def to_dict(self) -> dict:
        return {
            'name':             self.name,
            'cash':             self.cash,
            'starting_balance': self.starting_balance,
            'total_equity':     self.total_equity,
            'total_pnl':        self.total_pnl,
            'total_pnl_pct':    self.total_pnl_pct,
            'positions':        {k: v.to_dict() for k, v in self.positions.items()},
            'trade_history':    self.trade_history,
            'equity_curve':     self.equity_curve[-200:],  # last 200 points
        }


# =============================================================================
# POSITION
# =============================================================================

class Position:
    def __init__(self, symbol: str, qty: float, avg_price: float,
                 stop_loss: Optional[float] = None,
                 take_profit: Optional[float] = None,
                 trailing_stop_pct: Optional[float] = None):
        self.symbol           = symbol
        self.qty              = qty
        self.avg_price        = avg_price
        self.current_price    = avg_price
        self.stop_loss        = stop_loss
        self.take_profit      = take_profit
        self.trailing_stop_pct= trailing_stop_pct
        self.high_water_mark  = avg_price   # for trailing stop
        self.opened_at        = _now()

    @property
    def current_value(self) -> float:
        return round(self.qty * self.current_price, 4)

    @property
    def unrealized_pnl(self) -> float:
        return round((self.current_price - self.avg_price) * self.qty, 4)

    @property
    def unrealized_pnl_pct(self) -> float:
        return round(((self.current_price - self.avg_price) / self.avg_price) * 100, 2) \
               if self.avg_price > 0 else 0.0

    def update_price(self, new_price: float):
        self.current_price = new_price
        if new_price > self.high_water_mark:
            self.high_water_mark = new_price
        # Update trailing stop
        if self.trailing_stop_pct:
            new_trail = self.high_water_mark * (1 - self.trailing_stop_pct)
            if self.stop_loss is None or new_trail > self.stop_loss:
                self.stop_loss = round(new_trail, 6)

    def should_stop_loss(self) -> bool:
        return self.stop_loss is not None and self.current_price <= self.stop_loss

    def should_take_profit(self) -> bool:
        return self.take_profit is not None and self.current_price >= self.take_profit

    def to_dict(self) -> dict:
        return {
            'symbol':             self.symbol,
            'qty':                self.qty,
            'avg_price':          self.avg_price,
            'current_price':      self.current_price,
            'current_value':      self.current_value,
            'unrealized_pnl':     self.unrealized_pnl,
            'unrealized_pnl_pct': self.unrealized_pnl_pct,
            'stop_loss':          self.stop_loss,
            'take_profit':        self.take_profit,
            'trailing_stop_pct':  self.trailing_stop_pct,
            'high_water_mark':    self.high_water_mark,
            'opened_at':          self.opened_at,
        }


# =============================================================================
# PAPER TRADER ENGINE
# =============================================================================

class PaperTrader:

    def __init__(self):
        self.stock_account  = Account('Stocks',  STOCK_BAL)
        self.crypto_account = Account('Cryptos', CRYPTO_BAL)
        self._load_state()

    def _account(self, asset_type: str) -> Account:
        return self.stock_account if asset_type == 'stock' else self.crypto_account

    # ── Order execution ───────────────────────────────────────────────────────

    def place_order(
        self,
        asset_type:        str,     # 'stock' or 'crypto'
        symbol:            str,
        side:              str,     # 'buy' or 'sell'
        order_type:        str,     # 'market' or 'limit'
        qty:               float,
        limit_price:       Optional[float] = None,
        market_price:      float = 0.0,
        stop_loss:         Optional[float] = None,
        take_profit:       Optional[float] = None,
        trailing_stop_pct: Optional[float] = None,
    ) -> dict:
        """Place a paper order. Returns fill result dict."""

        acct = self._account(asset_type)
        acct.order_counter += 1
        order_id = f"{asset_type[0].upper()}{acct.order_counter:04d}"

        # Determine execution price
        if order_type == OrderType.MARKET:
            exec_price = self._apply_slippage(market_price, side)
        else:
            if limit_price is None:
                return self._reject(order_id, "Limit order requires limit_price")
            # Limit buy fills if market <= limit; limit sell fills if market >= limit
            if side == OrderSide.BUY  and market_price > limit_price:
                return self._reject(order_id, "Limit buy: market price above limit")
            if side == OrderSide.SELL and market_price < limit_price:
                return self._reject(order_id, "Limit sell: market price below limit")
            exec_price = limit_price

        # Partial fill simulation (limit orders only)
        filled_qty = qty
        if order_type == OrderType.LIMIT and random.random() < PARTIAL_CHANCE:
            fill_pct   = random.uniform(PARTIAL_MIN, PARTIAL_MAX)
            filled_qty = round(qty * fill_pct, 6)
            logger.info(f"Partial fill: {fill_pct*100:.0f}% of {qty}")

        cost = exec_price * filled_qty

        if side == OrderSide.BUY:
            if cost > acct.cash:
                return self._reject(order_id, f"Insufficient cash (need ${cost:.2f}, have ${acct.cash:.2f})")
            acct.cash -= cost
            self._open_or_add(acct, symbol, filled_qty, exec_price,
                              stop_loss, take_profit, trailing_stop_pct)

        else:  # SELL
            if symbol not in acct.positions:
                return self._reject(order_id, f"No position in {symbol}")
            pos = acct.positions[symbol]
            sell_qty = min(filled_qty, pos.qty)
            proceeds = exec_price * sell_qty
            acct.cash += proceeds
            trade = self._close_position(acct, symbol, sell_qty, exec_price)

        acct.snapshot_equity()
        self._save_state()

        result = {
            'order_id':    order_id,
            'status':      'filled',
            'symbol':      symbol,
            'side':        side,
            'order_type':  order_type,
            'requested_qty': qty,
            'filled_qty':  filled_qty,
            'exec_price':  round(exec_price, 6),
            'total_cost':  round(exec_price * filled_qty, 4),
            'timestamp':   _now(),
            'cash_after':  round(acct.cash, 4),
            'equity_after':acct.total_equity,
        }

        logger.info(f"FILL [{order_id}] {side.upper()} {filled_qty} {symbol} @ ${exec_price:.4f}")
        self._record_trade(result, asset_type)
        return result

    def _open_or_add(self, acct, symbol, qty, price, sl, tp, trail):
        if symbol in acct.positions:
            pos = acct.positions[symbol]
            new_qty   = pos.qty + qty
            new_avg   = (pos.avg_price * pos.qty + price * qty) / new_qty
            pos.qty   = new_qty
            pos.avg_price = new_avg
        else:
            acct.positions[symbol] = Position(
                symbol, qty, price,
                stop_loss=sl,
                take_profit=tp,
                trailing_stop_pct=trail if trail else TRAIL_PCT,
            )

    def _close_position(self, acct, symbol, qty, price) -> dict:
        pos = acct.positions[symbol]
        realized_pnl = (price - pos.avg_price) * qty
        trade = {
            'symbol':        symbol,
            'qty':           qty,
            'avg_price':     pos.avg_price,
            'exit_price':    price,
            'realized_pnl':  round(realized_pnl, 4),
            'pnl_pct':       round((price - pos.avg_price) / pos.avg_price * 100, 2),
            'opened_at':     pos.opened_at,
            'closed_at':     _now(),
        }
        if qty >= pos.qty:
            del acct.positions[symbol]
        else:
            pos.qty -= qty
        acct.trade_history.append(trade)
        return trade

    def _apply_slippage(self, price: float, side: str) -> float:
        slip = price * SLIPPAGE
        return round(price + slip if side == OrderSide.BUY else price - slip, 6)

    def _reject(self, order_id: str, reason: str) -> dict:
        logger.warning(f"Order {order_id} REJECTED: {reason}")
        return {'order_id': order_id, 'status': 'rejected', 'reason': reason}

    # ── Price updates + stop/TP checks ───────────────────────────────────────

    def update_prices(self, asset_type: str, price_map: dict):
        """Update position prices and trigger stop-loss / take-profit."""
        acct     = self._account(asset_type)
        to_close = []

        for symbol, pos in acct.positions.items():
            if symbol not in price_map:
                continue
            new_price = price_map[symbol]
            pos.update_price(new_price)

            if pos.should_stop_loss():
                logger.info(f"STOP-LOSS triggered: {symbol} @ ${new_price}")
                to_close.append((symbol, new_price, 'stop_loss'))
            elif pos.should_take_profit():
                logger.info(f"TAKE-PROFIT triggered: {symbol} @ ${new_price}")
                to_close.append((symbol, new_price, 'take_profit'))

        for symbol, price, reason in to_close:
            pos  = acct.positions[symbol]
            qty  = pos.qty
            exec_price = self._apply_slippage(price, OrderSide.SELL)
            acct.cash += exec_price * qty
            trade = self._close_position(acct, symbol, qty, exec_price)
            trade['close_reason'] = reason
            logger.info(f"Auto-closed {symbol} ({reason}): P&L ${trade['realized_pnl']}")
            self._record_trade({
                'symbol': symbol, 'side': 'sell', 'filled_qty': qty,
                'exec_price': exec_price, 'timestamp': _now(),
            }, asset_type)

        acct.snapshot_equity()
        self._save_state()

    # ── Modify orders ─────────────────────────────────────────────────────────

    def modify_position(self, asset_type: str, symbol: str,
                        stop_loss: Optional[float] = None,
                        take_profit: Optional[float] = None,
                        trailing_stop_pct: Optional[float] = None) -> dict:
        acct = self._account(asset_type)
        if symbol not in acct.positions:
            return {'status': 'error', 'reason': f'No position in {symbol}'}
        pos = acct.positions[symbol]
        if stop_loss          is not None: pos.stop_loss          = stop_loss
        if take_profit        is not None: pos.take_profit        = take_profit
        if trailing_stop_pct  is not None: pos.trailing_stop_pct  = trailing_stop_pct
        self._save_state()
        return {'status': 'ok', 'symbol': symbol, 'position': pos.to_dict()}

    # ── Portfolio summary ─────────────────────────────────────────────────────

    def get_portfolio(self) -> dict:
        return {
            'stocks':  self.stock_account.to_dict(),
            'cryptos': self.crypto_account.to_dict(),
            'combined_equity': round(
                self.stock_account.total_equity + self.crypto_account.total_equity, 4),
            'combined_pnl': round(
                self.stock_account.total_pnl + self.crypto_account.total_pnl, 4),
        }

    # ── CSV export ────────────────────────────────────────────────────────────

    def export_csv(self, filepath: str = None):
        path = filepath or TRADES_FILE
        all_trades = (
            [{'account':'Stocks',  **t} for t in self.stock_account.trade_history]  +
            [{'account':'Cryptos', **t} for t in self.crypto_account.trade_history]
        )
        if not all_trades:
            logger.info("No trades to export")
            return path

        fields = ['account','symbol','qty','avg_price','exit_price',
                  'realized_pnl','pnl_pct','opened_at','closed_at']
        with open(path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            w.writerows(all_trades)
        logger.info(f"Exported {len(all_trades)} trades to {path}")
        return path

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_state(self):
        try:
            with open(PORTFOLIO_FILE, 'w') as f:
                json.dump(self.get_portfolio(), f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save portfolio state: {e}")

    def _load_state(self):
        try:
            with open(PORTFOLIO_FILE) as f:
                state = json.load(f)
            # Restore stock account
            sa = state.get('stocks', {})
            self.stock_account.cash = sa.get('cash', STOCK_BAL)
            self.stock_account.equity_curve = sa.get('equity_curve', self.stock_account.equity_curve)
            self.stock_account.trade_history = sa.get('trade_history', [])
            for sym, pd_ in sa.get('positions', {}).items():
                pos = Position(sym, pd_['qty'], pd_['avg_price'],
                               pd_.get('stop_loss'), pd_.get('take_profit'),
                               pd_.get('trailing_stop_pct'))
                pos.current_price   = pd_.get('current_price', pd_['avg_price'])
                pos.high_water_mark = pd_.get('high_water_mark', pd_['avg_price'])
                self.stock_account.positions[sym] = pos
            # Restore crypto account
            ca = state.get('cryptos', {})
            self.crypto_account.cash = ca.get('cash', CRYPTO_BAL)
            self.crypto_account.equity_curve = ca.get('equity_curve', self.crypto_account.equity_curve)
            self.crypto_account.trade_history = ca.get('trade_history', [])
            for sym, pd_ in ca.get('positions', {}).items():
                pos = Position(sym, pd_['qty'], pd_['avg_price'],
                               pd_.get('stop_loss'), pd_.get('take_profit'),
                               pd_.get('trailing_stop_pct'))
                pos.current_price   = pd_.get('current_price', pd_['avg_price'])
                pos.high_water_mark = pd_.get('high_water_mark', pd_['avg_price'])
                self.crypto_account.positions[sym] = pos
            logger.info("Portfolio state loaded from disk")
        except FileNotFoundError:
            logger.info("No saved portfolio state — starting fresh")
        except Exception as e:
            logger.warning(f"Could not load portfolio state: {e}")

    def _record_trade(self, result: dict, asset_type: str):
        pass  # Already stored in trade_history via _close_position


# =============================================================================
# HELPERS
# =============================================================================

def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

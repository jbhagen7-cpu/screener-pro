# =============================================================================
# app.py — Stock & Crypto Screener Pro
# Flask server + screener orchestrator
# Serves screening results to the dashboard at /api/screening_results.json
# =============================================================================

import json
import logging
import os
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from data_connector  import DataConnector
from market_screener import MarketScreener
from paper_trader    import PaperTrader

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
try:
    import config as cfg
    TOP_N_STOCKS      = cfg.TOP_N_STOCKS
    TOP_N_CRYPTOS     = cfg.TOP_N_CRYPTOS
    RESULTS_FILE      = cfg.RESULTS_FILE
    REFRESH_INTERVAL  = cfg.AUTO_REFRESH_INTERVAL_MINUTES * 60
except ImportError:
    TOP_N_STOCKS     = 5
    TOP_N_CRYPTOS    = 5
    RESULTS_FILE     = 'screening_results.json'
    REFRESH_INTERVAL = 300  # 5 min

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder='.')
CORS(app)  # Allow dashboard to call API from any origin

# ── Global state ──────────────────────────────────────────────────────────────
connector = DataConnector()
screener  = MarketScreener()
trader    = PaperTrader()

_last_results  = None
_last_scan_time = None
_scan_lock     = threading.Lock()
_scanning      = False


# =============================================================================
# SCREENER LOGIC
# =============================================================================

def run_scan() -> dict:
    global _last_results, _last_scan_time, _scanning

    with _scan_lock:
        if _scanning:
            logger.info("Scan already in progress — skipping")
            return _last_results or {}
        _scanning = True

    try:
        logger.info("=== Starting market scan ===")
        start = time.time()

        # 1. Fetch raw data
        raw = connector.scan_all()

        # 2. Score + rank
        top_stocks  = screener.screen_stocks(raw['stocks'],  TOP_N_STOCKS)
        top_cryptos = screener.screen_cryptos(raw['cryptos'], TOP_N_CRYPTOS)

        # 3. Update paper trader prices
        stock_prices  = {s['symbol']: s['price'] for s in raw['stocks']}
        crypto_prices = {c['symbol']: c['price'] for c in raw['cryptos']}
        trader.update_prices('stock',  stock_prices)
        trader.update_prices('crypto', crypto_prices)

        # 4. Build result payload
        results = {
            'stocks':      top_stocks,
            'cryptos':     top_cryptos,
            'scanned_at':  datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'scan_duration_sec': round(time.time() - start, 1),
            'total_scanned': {
                'stocks':  len(raw['stocks']),
                'cryptos': len(raw['cryptos']),
            },
            'portfolio': trader.get_portfolio(),
        }

        # 5. Save to disk
        with open(RESULTS_FILE, 'w') as f:
            json.dump(results, f, indent=2)

        _last_results   = results
        _last_scan_time = datetime.now()
        logger.info(f"Scan complete in {results['scan_duration_sec']}s — "
                    f"{len(top_stocks)} stocks, {len(top_cryptos)} cryptos")
        return results

    except Exception as e:
        logger.error(f"Scan failed: {e}", exc_info=True)
        return _last_results or {}
    finally:
        _scanning = False


def background_scanner():
    """Runs scan on startup then every REFRESH_INTERVAL seconds."""
    logger.info(f"Background scanner started — interval: {REFRESH_INTERVAL}s")
    while True:
        try:
            run_scan()
        except Exception as e:
            logger.error(f"Background scan error: {e}")
        time.sleep(REFRESH_INTERVAL)


# =============================================================================
# API ROUTES
# =============================================================================

@app.route('/api/screening_results.json')
def api_results():
    """Main endpoint — returns latest screening results as JSON."""
    if _last_results:
        return jsonify(_last_results)
    # If no results yet, return placeholder
    return jsonify({
        'stocks':     [],
        'cryptos':    [],
        'scanned_at': None,
        'status':     'scanning',
        'message':    'First scan in progress — check back in ~60 seconds',
    })


@app.route('/api/portfolio')
def api_portfolio():
    """Return paper trading portfolio state."""
    return jsonify(trader.get_portfolio())


@app.route('/api/trade', methods=['POST'])
def api_trade():
    """Place a paper trade."""
    from flask import request
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    result = trader.place_order(
        asset_type        = data.get('asset_type', 'stock'),
        symbol            = data.get('symbol', ''),
        side              = data.get('side', 'buy'),
        order_type        = data.get('order_type', 'market'),
        qty               = float(data.get('qty', 0)),
        limit_price       = data.get('limit_price'),
        market_price      = float(data.get('market_price', 0)),
        stop_loss         = data.get('stop_loss'),
        take_profit       = data.get('take_profit'),
        trailing_stop_pct = data.get('trailing_stop_pct'),
    )
    return jsonify(result)


@app.route('/api/export_csv')
def api_export_csv():
    """Export trade history as CSV download."""
    path = trader.export_csv()
    return send_from_directory('.', path, as_attachment=True,
                               download_name='trades_export.csv')


@app.route('/api/scan_now')
def api_scan_now():
    """Force an immediate re-scan (async)."""
    t = threading.Thread(target=run_scan, daemon=True)
    t.start()
    return jsonify({'status': 'scan started', 'timestamp': datetime.now().isoformat()})


@app.route('/api/status')
def api_status():
    """Health check + last scan info."""
    return jsonify({
        'status':         'ok',
        'last_scan':      _last_scan_time.isoformat() if _last_scan_time else None,
        'scanning':       _scanning,
        'refresh_interval_sec': REFRESH_INTERVAL,
        'top_stocks':     [s.get('symbol') for s in (_last_results or {}).get('stocks',  [])],
        'top_cryptos':    [c.get('symbol') for c in (_last_results or {}).get('cryptos', [])],
    })


@app.route('/api/test/<ticker>')
def test_ticker(ticker):
    """Returns raw price data for a specific ticker to confirm connectivity."""
    try:
        data = connector.stocks.fetch(ticker.upper())
        if data:
            return jsonify({'status': 'success', 'ticker': ticker.upper(), 'data': data}), 200
        else:
            return jsonify({'status': 'error', 'message': f'No data found for {ticker}'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    """Modify stop-loss / take-profit on an open position."""
    from flask import request
    data = request.get_json()
    result = trader.modify_position(
        asset_type        = data.get('asset_type', 'stock'),
        symbol            = data.get('symbol', ''),
        stop_loss         = data.get('stop_loss'),
        take_profit       = data.get('take_profit'),
        trailing_stop_pct = data.get('trailing_stop_pct'),
    )
    return jsonify(result)


# ── Serve static files (dashboard + config editor) ───────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'dashboard.html')

@app.route('/config')
def config_page():
    return send_from_directory('.', 'config_editor.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)


# =============================================================================
# STARTUP
# =============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))

    # Start background scanner in a daemon thread
    scan_thread = threading.Thread(target=background_scanner, daemon=True)
    scan_thread.start()

    logger.info(f"=== Screener Pro starting on port {port} ===")
    logger.info(f"Dashboard:     http://localhost:{port}/")
    logger.info(f"Config Editor: http://localhost:{port}/config")
    logger.info(f"API:           http://localhost:{port}/api/screening_results.json")

    app.run(host='0.0.0.0', port=port, debug=False)

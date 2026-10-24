"""Discover listed instruments from the provider, not from a hard-coded asset list.

Coverage is limited by listing history, exchange API, provider entitlements and
which instruments have OHLCV data. Discovery is not a promise of backtestability.
"""
from __future__ import annotations

from functools import lru_cache
import time


@lru_cache(maxsize=1)
def exchanges() -> list[str]:
    try:
        import ccxt
    except ImportError as e:
        raise RuntimeError("Install CCXT to discover exchange markets: pip install -e '.[cex]'") from e
    return sorted(ccxt.exchanges)


@lru_cache(maxsize=32)
def _ccxt_markets(exchange_id: str, market_type: str, bucket: int):
    import ccxt
    if exchange_id not in ccxt.exchanges:
        raise ValueError('Unknown exchange ID')
    client = getattr(ccxt, exchange_id)({
        'enableRateLimit': True, 'timeout': 15000,
        'options': {'defaultType': market_type}
    })
    try:
        result = client.load_markets()
        out = []
        for key, market in result.items():
            if not market.get('active', True):
                continue
            if market_type in ('spot','swap','future') and not market.get(market_type, False):
                continue
            out.append({'symbol': market.get('symbol') or key,
                        'base': market.get('base') or '',
                        'quote': market.get('quote') or '',
                        'type': market.get('type') or market_type,
                        'settle': market.get('settle') or '',
                        'exchange': exchange_id})
        return sorted(out, key=lambda x: x['symbol'])
    finally:
        if hasattr(client, 'close'):
            client.close()


def search_markets(provider: str, query: str, exchange_id: str = '',
                   market_type: str = 'swap', limit: int = 30) -> dict:
    query = query.strip()
    if not 1 <= len(query) <= 80:
        raise ValueError('Market search query must contain 1..80 characters')
    if not 1 <= limit <= 100:
        raise ValueError('limit must be 1..100')
    if provider == 'ccxt':
        if market_type not in ('spot', 'swap', 'future'):
            raise ValueError('market_type must be spot, swap or future')
        matches = _ccxt_markets(exchange_id, market_type, int(time.time() // 600))
        norm = query.casefold()
        ranked = [r for r in matches if norm in r['symbol'].casefold()
                  or norm in r['base'].casefold()
                  or norm in r['quote'].casefold()]
        return {'provider':'ccxt', 'exchange':exchange_id,
                'items':ranked[:limit], 'matched_count':len(ranked),
                'limitation': 'Only currently listed active instruments; history availability varies.'}
    if provider == 'hyperliquid':
        # Fetch the current native perp universe; no hardcoded list.
        names = _hyperliquid_universe(int(time.time() // 600))
        ranked = [x for x in names if query.casefold() in x['symbol'].casefold()]
        return {'provider':'hyperliquid','items':ranked[:limit], 'matched_count':len(ranked),
                'limitation':'Only currently listed native perpetuals; older history may be unavailable.'}
    if provider == 'yfinance':
        try:
            import yfinance as yf
        except ImportError as err:
            raise RuntimeError("Install yfinance: pip install -e '.[stocks]'") from err
        results = yf.Search(query, max_results=limit, news_count=0, lists_count=0, include_cb=False).quotes
        result = []
        for row in results[:limit]:
            symbol = str(row.get('symbol') or '').strip()
            if not symbol:
                continue
            result.append({'symbol':symbol,'name':str(row.get('shortname') or row.get('longname') or '')[:160],
                           'exchange':str(row.get('exchange') or '')[:40],
                           'type':str(row.get('quoteType') or '')[:32]})
        return {'provider':'yfinance', 'items':result, 'matched_count':len(result),
                'limitation':'Yahoo search does not cover every listed, delisted, OTC or private security.'}
    raise ValueError('Market discovery supports ccxt, hyperliquid and yfinance')


@lru_cache(maxsize=2)
def _hyperliquid_universe(bucket: int) -> list[dict]:
    import httpx
    with httpx.Client(timeout=15) as client:
        res = client.post('https://api.hyperliquid.xyz/info', json={'type':'meta'})
        res.raise_for_status()
        universe = res.json().get('universe', [])
    return [{'symbol':str(x['name']), 'type':'swap', 'exchange':'hyperliquid'}
            for x in universe if x.get('name') and not x.get('isDelisted')]
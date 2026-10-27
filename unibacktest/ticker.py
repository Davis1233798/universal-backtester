"""On-demand, source-labelled market quote for the trading workspace.

This is a best-effort REST quote, NOT an exchange WebSocket stream. Quote
timestamp, sample time and price type are explicit so last/mid/index cannot
be confused with the candle close or mark price.
"""
from __future__ import annotations

import math
import threading
import time
import httpx

_lock = threading.RLock()
_exchange_clients: dict[tuple[str,str], object] = {}
_quote_cache: dict[tuple[str,str,str,str], tuple[float,dict]] = {}
CACHE_SECONDS = 5


def current_quote(provider: str, exchange: str, symbol: str,
                  market_type: str = 'swap') -> dict:
    if len(symbol) > 128 or not symbol:
        raise ValueError('Invalid market symbol')
    key=(provider,exchange,symbol,market_type)
    now=time.time()
    with _lock:
        previous=_quote_cache.get(key)
        if previous and now-previous[0]<CACHE_SECONDS:
            return {**previous[1],"cached":True}
        if provider=='ccxt':
            import ccxt
            if exchange not in ccxt.exchanges:
                raise ValueError('Unknown CCXT exchange')
            ex_key=(exchange,market_type)
            client=_exchange_clients.get(ex_key)
            if client is None:
                client=getattr(ccxt,exchange)({
                    'enableRateLimit':True,'timeout':12000,
                    'options':{'defaultType':market_type}})
                client.load_markets()
                _exchange_clients[ex_key]=client
            if symbol not in client.markets:
                raise ValueError(f'{symbol} is not listed at {exchange}')
            if not client.has.get('fetchTicker'):
                raise ValueError(f'{exchange} has no ticker endpoint')
            ticker=client.fetch_ticker(symbol)
            last=ticker.get('last')
            if last is None or not isinstance(last,(int,float)) or not math.isfinite(last) or last<=0:
                raise ValueError('Exchange ticker has no finite LAST trade')
            timestamp=ticker.get('timestamp')
            output={'provider':provider,'exchange':exchange,
                    'symbol':symbol,'price_type':'last trade',
                    'price':float(last),'market_ts':int(timestamp) if timestamp else None,
                    'received_at_ms':int(now*1000)}
        elif provider=='hyperliquid':
            coin=symbol.split('/')[0]
            with httpx.Client(timeout=12) as client:
                response=client.post('https://api.hyperliquid.xyz/info',
                                     json={'type':'allMids'})
                response.raise_for_status()
                prices=response.json()
            if not isinstance(prices,dict) or coin not in prices:
                raise ValueError('Hyperliquid mid-price unavailable for '+coin)
            price=float(prices[coin])
            if not math.isfinite(price) or price<=0:
                raise ValueError('Invalid Hyperliquid midpoint')
            output={'provider':provider,'exchange':'hyperliquid','symbol':symbol,
                    'price_type':'mid (not last trade)','price':price,
                    'market_ts':None,'received_at_ms':int(now*1000)}
        else:
            raise ValueError('Live quotes support CCXT and Hyperliquid only')
        _quote_cache[key]=(now,output)
        return {**output,'cached':False}

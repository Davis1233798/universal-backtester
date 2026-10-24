"""Simple extension example. Launch from project root with PYTHONPATH=examples:.
Config: data.provider="plugin:vendor_adapter" and UBT_ALLOW_EXEC=1.
Replace this with authenticated Polygon, EODHD, TWSE, GMX indexer, etc.
"""
from unibacktest.adapters import from_csv

def fetch(req):
    # Any vendor implementation must return validated unibacktest.model.Bar objects.
    return from_csv(req)

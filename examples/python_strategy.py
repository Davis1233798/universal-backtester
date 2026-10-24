"""Trusted Python plugin example. Enable with UBT_ALLOW_EXEC=1."""
def on_bar(ctx):
    closes = [b['close'] for b in ctx['bars']]
    if len(closes) < 20:
        return 0.0
    return 1.0 if closes[-1] > sum(closes[-20:]) / 20 else 0.0

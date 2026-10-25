"""Deliberately restricted, interpreter-only Pine-like strategy subset.

Supports common strategy.entry/close, indicator expressions and closed-bar signals.
No eval, exec, attribute lookup on arbitrary objects, imports, loops or file I/O.
Unsupported constructs MUST raise instead of silently producing wrong trades.
Not a complete TradingView Pine Script runtime.
"""
from __future__ import annotations

import ast
import math
import re
from typing import Any

_ALLOWED_FUNCTIONS = {
    'ta.sma', 'ta.ema', 'ta.rsi', 'ta.highest', 'ta.lowest',
    'ta.crossover', 'ta.crossunder', 'ta.cross', 'ta.change',
    'math.abs', 'math.min', 'math.max', 'abs', 'min', 'max',
    'input.int', 'input.float', 'input.bool', 'input.source',
    'nz', 'na', 'strategy.entry', 'strategy.close', 'strategy.close_all', 'strategy.exit',
    'strategy.order', 'strategy.cancel', 'strategy.cancel_all',
    'plot', 'plotshape', 'plotchar', 'hline', 'bgcolor', 'barcolor', 'alertcondition',
}
_SAFE_NAMES = {'open', 'high', 'low', 'close', 'volume', 'time', 'bar_index',
               'true', 'false', 'na', 'strategy.long', 'strategy.short',
               'strategy.position_size', 'strategy.position_avg_price'}
_ASSIGN_RE = re.compile(r'^(?:varip\s+|var\s+)?(?:int\s+|float\s+|bool\s+|string\s+)?([A-Za-z_][\w]*)\s*(?::=|=)')


def _function_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id + '.' + node.attr
    return ''


def _check_expr(node: ast.AST, names: set[str], budget: list[int]):
    budget[0] += 1
    if budget[0] > 600:
        raise ValueError('Pine expression is too complex')
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (float, int, bool, str, type(None))):
            raise ValueError('Unsupported Pine constant')
        if isinstance(node.value, str) and len(node.value) > 200:
            raise ValueError('Pine string too long')
    elif isinstance(node, ast.Name):
        if node.id not in names and node.id not in _SAFE_NAMES:
            raise ValueError(f'Unknown Pine identifier: {node.id}')
    elif isinstance(node, ast.Attribute):
        if _function_name(node) not in _SAFE_NAMES:
            raise ValueError(f'Unsupported Pine attribute: {_function_name(node)}')
    elif isinstance(node, ast.Call):
        name = _function_name(node.func)
        if name not in _ALLOWED_FUNCTIONS:
            raise ValueError(f'Unsupported Pine function: {name}')
        if len(node.args) + len(node.keywords) > 8:
            raise ValueError('Too many Pine function parameters')
        for arg in node.args:
            _check_expr(arg, names, budget)
        for kw in node.keywords:
            if kw.arg is None:
                raise ValueError('Pine dynamic arguments are unsupported')
            _check_expr(kw.value, names, budget)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)):
        _check_expr(node.left, names, budget)
        _check_expr(node.right, names, budget)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
        _check_expr(node.operand, names, budget)
    elif isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        for v in node.values: _check_expr(v, names, budget)
    elif isinstance(node, ast.Compare) and len(node.ops) <= 2 and all(isinstance(op, (ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq)) for op in node.ops):
        _check_expr(node.left, names, budget)
        for v in node.comparators: _check_expr(v, names, budget)
    elif isinstance(node, ast.IfExp):
        _check_expr(node.test, names, budget)
        _check_expr(node.body, names, budget)
        _check_expr(node.orelse, names, budget)
    elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and type(node.slice.value) is int and 0 <= node.slice.value:
        _check_expr(node.value, names, budget)
    else:
        raise ValueError(f'Unsupported Pine syntax: {node.__class__.__name__}')


def _validate_statements(body: list[ast.stmt], names: set[str], budget: list[int]):
    for stmt in body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            name = stmt.targets[0].id
            if name in _SAFE_NAMES or name.startswith('__'):
                raise ValueError(f'Cannot assign built-in: {name}')
            _check_expr(stmt.value, names, budget)
            names.add(name)
        elif isinstance(stmt, ast.If):
            _check_expr(stmt.test, names, budget)
            _validate_statements(stmt.body, names.copy(), budget)
            _validate_statements(stmt.orelse, names.copy(), budget)
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            name = _function_name(stmt.value.func)
            if name not in ('strategy.entry', 'strategy.close', 'strategy.close_all', 'strategy.exit',
                            'plot', 'plotshape', 'plotchar', 'hline', 'bgcolor', 'barcolor', 'alertcondition'):
                raise ValueError(f'Unsupported Pine statement: {name}')
            _check_expr(stmt.value, names, budget)
        else:
            raise ValueError(f'Unsupported Pine statement: {stmt.__class__.__name__}')


def parse_pine(code: str) -> tuple[list[ast.stmt], set[str]]:
    if not isinstance(code, str) or len(code) > 12_000:
        raise ValueError('Pine code must be a string of at most 12,000 characters')
    lines, persistent = [], set()
    for raw in code.splitlines():
        if raw.strip().startswith('//') or not raw.strip():
            continue
        if '\t' in raw:
            raw = raw.expandtabs(4)
        # Disallow multi-statement chains and unsupported special operators.
        if ';' in raw or '=>' in raw:
            raise ValueError('Pine inline functions and multiple statements are unsupported')
        indent = len(raw) - len(raw.lstrip())
        if indent % 4 != 0:
            raise ValueError('Pine indentation must use multiples of 4 spaces')
        src = raw.strip()
        if src.startswith('strategy('):
            if indent:
                raise ValueError('strategy header must be top-level')
            continue
        if src.startswith('indicator('):
            raise ValueError('indicator() scripts cannot place trades; use strategy()')
        if src.startswith('else if '):
            src = 'elif ' + src[8:]
        if src.startswith(('if ', 'elif ')) or src == 'else':
            if not src.endswith(':'):
                src += ':'
        match = _ASSIGN_RE.match(src)
        if match:
            if re.match(r'^var(?:ip)?\s+', src):
                persistent.add(match.group(1))
            src = re.sub(r'^(?:varip\s+|var\s+)?(?:int\s+|float\s+|bool\s+|string\s+)?', '', src).replace(':=', '=', 1)
        lines.append(' ' * indent + src)
    if len(lines) > 120:
        raise ValueError('Pine public subset limited to 120 statements')
    try:
        tree = ast.parse('\n'.join(lines))
    except SyntaxError as err:
        raise ValueError(f'Unsupported Pine syntax near line {err.lineno}: {err.msg}') from err
    names = set()
    _validate_statements(tree.body, names, [0])
    if not any(_function_name(stmt.value.func).startswith('strategy.')
               for stmt in ast.walk(tree) if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        raise ValueError('Pine strategy needs at least one strategy.entry/close order')
    return tree.body, persistent


class PineSubsetStrategy:
    """Stateless-safe parser; persistent state only in this in-memory backtest instance."""
    def __init__(self, code: str, inputs: dict | None = None):
        self.history_all = True
        self.body, self.persistent = parse_pine(code)
        if inputs and (not isinstance(inputs, dict) or len(inputs) > 30):
            raise ValueError('Pine inputs must be an object of at most 30 entries')
        self.inputs = inputs or {}
        self.history_depth = max(
            (node.slice.value for statement in self.body for node in ast.walk(statement)
             if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
             and type(node.slice.value) is int), default=0) + 1
        # Infer simple constant/input indicator lengths for bounded streaming.
        known={}
        periods=[]
        dynamic=False
        for stmt in self.body:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name):
                expr=stmt.value
                if isinstance(expr, ast.Constant) and type(expr.value) is int:
                    known[stmt.targets[0].id]=expr.value
                if isinstance(expr, ast.Call) and _function_name(expr.func)=="input.int":
                    default=expr.args[0].value if expr.args and isinstance(expr.args[0],ast.Constant) else None
                    title=(expr.args[1].value if len(expr.args)>1 and
                           isinstance(expr.args[1],ast.Constant) else None)
                    known[stmt.targets[0].id]=self.inputs.get(str(title),default) if inputs else default
        for stmt in self.body:
            for node in ast.walk(stmt):
                if isinstance(node,ast.Call) and _function_name(node.func) in (
                    "ta.sma","ta.ema","ta.rsi","ta.highest","ta.lowest","ta.change"):
                    arg=node.args[1] if len(node.args)>1 else None
                    value=(arg.value if isinstance(arg,ast.Constant) else
                           known.get(arg.id) if isinstance(arg,ast.Name) else
                           1 if arg is None and _function_name(node.func)=="ta.change" else None)
                    if type(value) is int and value>=1:
                        periods.append(value)
                    else:
                        dynamic=True
        # Dynamic lookbacks cannot be guaranteed bounded without a declared
        # max; full-history mode still supports them.
        self.streaming_window=None if dynamic else max(
            500,self.history_depth+2,max(periods,default=1)+110)
        self.variables: dict[str, Any] = {}
        self.history: dict[str, list[Any]] = {}
        self._initialized: set[str] = set()
        self.ctx: dict = {}
        self.ops = 0
        self.target = 0.0
        self.bar_index = -1
        self.order_event = None

    def _limit(self):
        self.ops += 1
        if self.ops > 50000:
            raise ValueError('Pine strategy exceeded per-bar calculation limit')

    def _value(self, expr: ast.AST, offset=0, depth=0):
        self._limit()
        if depth > 24 or offset < 0:
            raise ValueError('Pine expression depth exceeded or negative lookback')
        at = lambda n, off=offset: self._value(n, off, depth+1)
        if isinstance(expr, ast.Constant): return expr.value
        if isinstance(expr, ast.Name):
            name = expr.id
            if name == 'true': return True
            if name == 'false': return False
            if name == 'na': return None
            if name == 'bar_index': return self.bar_index - offset
            if name in ('open', 'high', 'low', 'close', 'volume', 'time'):
                bars = self.ctx['bars']
                if offset >= len(bars): return None
                return bars[-1-offset]['ts' if name == 'time' else name]
            if offset:
                hist = self.history.get(name, [])
                return hist[-offset] if len(hist) >= offset else None
            return self.variables.get(name)
        if isinstance(expr, ast.Attribute):
            name = _function_name(expr)
            if name == 'strategy.long': return 1.0
            if name == 'strategy.short': return -1.0
            if name == 'strategy.position_size': return self.ctx.get('position', 0)
            if name == 'strategy.position_avg_price': return self.ctx.get('avg_price', 0)
            raise ValueError(f'Pine unsupported field: {name}')
        if isinstance(expr, ast.Subscript):
            return at(expr.value, offset + expr.slice.value)
        if isinstance(expr, ast.UnaryOp):
            v=at(expr.operand)
            if isinstance(expr.op, ast.Not): return not bool(v)
            if v is None: return None
            return -v if isinstance(expr.op, ast.USub) else +v
        if isinstance(expr, ast.BoolOp):
            if isinstance(expr.op, ast.And): return all(bool(at(n)) for n in expr.values)
            return any(bool(at(n)) for n in expr.values)
        if isinstance(expr, ast.BinOp):
            x, y = at(expr.left), at(expr.right)
            if x is None or y is None: return None
            try:
                if isinstance(expr.op, ast.Add): return x+y
                if isinstance(expr.op, ast.Sub): return x-y
                if isinstance(expr.op, ast.Mult): return x*y
                if isinstance(expr.op, ast.Div): return x/y if y else None
                if isinstance(expr.op, ast.Mod): return x%y if y else None
                if isinstance(expr.op, ast.Pow):
                    if abs(float(y)) > 12: raise ValueError('Pine exponent too large')
                    out = x**y
                    return out if isinstance(out, (int,float)) and math.isfinite(out) else None
            except (OverflowError, TypeError, ValueError): return None
        if isinstance(expr, ast.IfExp): return at(expr.body if at(expr.test) else expr.orelse)
        if isinstance(expr, ast.Compare):
            lhs = at(expr.left)
            for op, rhs_expr in zip(expr.ops, expr.comparators):
                rhs = at(rhs_expr)
                if lhs is None or rhs is None: return False
                try:
                    if isinstance(op, ast.Gt): ok = lhs > rhs
                    elif isinstance(op, ast.GtE): ok = lhs >= rhs
                    elif isinstance(op, ast.Lt): ok = lhs < rhs
                    elif isinstance(op, ast.LtE): ok = lhs <= rhs
                    elif isinstance(op, ast.Eq): ok = lhs == rhs
                    else: ok = lhs != rhs
                except TypeError: return False
                if not ok: return False
                lhs=rhs
            return True
        if isinstance(expr, ast.Call):
            name = _function_name(expr.func)
            if name.startswith('input.'):
                default = at(expr.args[0]) if expr.args else None
                key = at(expr.args[1]) if len(expr.args)>1 else None
                if key is None:
                    for kw in expr.keywords:
                        if kw.arg == 'title': key = at(kw.value)
                answer = self.inputs.get(str(key), default)
                if name == 'input.bool':
                    if not isinstance(answer,bool): raise ValueError('Pine boolean input must be true/false')
                    return answer
                if name == 'input.int' and (type(answer) is not int or answer < 1):
                    raise ValueError('Pine integer input must be positive')
                if name == 'input.float' and (isinstance(answer,bool) or not isinstance(answer,(float,int)) or not math.isfinite(answer)):
                    raise ValueError('Pine float input must be finite')
                return answer
            if name in ('ta.crossover', 'ta.crossunder', 'ta.cross'):
                if len(expr.args) != 2: raise ValueError('Pine cross requires 2 arguments')
                a, b = at(expr.args[0]), at(expr.args[1])
                ap, bp = at(expr.args[0],offset+1), at(expr.args[1],offset+1)
                if None in (a, b, ap, bp): return False
                up = a > b and ap <= bp
                down = a < b and ap >= bp
                return up if name == 'ta.crossover' else down if name == 'ta.crossunder' else up or down
            if name in ('ta.sma','ta.ema','ta.highest','ta.lowest','ta.rsi'):
                if len(expr.args) != 2: raise ValueError(f'{name} requires 2 arguments')
                period = at(expr.args[1])
                if type(period) not in (int,float) or not math.isfinite(period) or int(period) != period or period < 1:
                    raise ValueError('Pine lookback must be a positive integer')
                n = int(period)
                if name == 'ta.rsi':
                    if n < 2: raise ValueError('RSI requires period >= 2')
                    values = [at(expr.args[0], offset+i) for i in range(n,-1,-1)]
                    if any(v is None for v in values): return None
                    diffs = [values[i+1]-values[i] for i in range(n)]
                    gains = sum(max(x,0) for x in diffs)/n
                    losses = sum(max(-x,0) for x in diffs)/n
                    return 100 if losses == 0 else 100-100/(1+gains/losses)
                values = [at(expr.args[0], offset+i) for i in range(n-1,-1,-1)]
                if any(v is None for v in values): return None
                if name == 'ta.sma': return sum(values)/n
                if name == 'ta.highest': return max(values)
                if name == 'ta.lowest': return min(values)
                # EMA warm-up is bounded by provided historical bar context.
                warm = min(100, len(self.ctx['bars'])-offset-n)
                if warm>0:
                    extra = [at(expr.args[0], offset+i) for i in range(n+warm-1,n-1,-1)]
                    values = [v for v in extra if v is not None]+values
                ema=values[0]
                for x in values[1:]: ema = (2/(n+1))*x + (1-2/(n+1))*ema
                return ema
            if name == 'ta.change':
                if len(expr.args) not in (1,2): raise ValueError('ta.change requires 1 or 2 arguments')
                lookback=at(expr.args[1]) if len(expr.args)==2 else 1
                if type(lookback) is not int or lookback < 1: raise ValueError('Invalid change lookback')
                x,old=at(expr.args[0]),at(expr.args[0],offset+lookback)
                return x-old if x is not None and old is not None else None
            if name in ('na','nz'):
                value=at(expr.args[0]) if expr.args else None
                if name == 'na': return value is None
                return at(expr.args[1]) if value is None and len(expr.args)>1 else (0 if value is None else value)
            if name in ('abs','min','max','math.abs','math.min','math.max'):
                values = [at(arg) for arg in expr.args]
                if any(v is None for v in values) or not values: return None
                if name in ('abs','math.abs'): return abs(values[0])
                return min(values) if name in ('min','math.min') else max(values)
            raise ValueError(f'Pine call not valid in an expression: {name}')
        raise ValueError(f'Unsupported Pine runtime expression {expr.__class__.__name__}')

    def _run(self, statements: list[ast.stmt]):
        for stmt in statements:
            self._limit()
            if isinstance(stmt, ast.Assign):
                name = stmt.targets[0].id
                if name in self.persistent and name in self._initialized: continue
                self.variables[name] = self._value(stmt.value)
                if name in self.persistent: self._initialized.add(name)
            elif isinstance(stmt, ast.If):
                self._run(stmt.body if self._value(stmt.test) else stmt.orelse)
            elif isinstance(stmt, ast.Expr):
                call=stmt.value
                fn=_function_name(call.func)
                if fn.startswith(('plot','hline','bgcolor','barcolor','alertcondition')):
                    continue
                if fn == 'strategy.entry':
                    if len(call.args) < 2: raise ValueError('strategy.entry requires id and direction')
                    direction=self._value(call.args[1])
                    if direction not in (-1,1): raise ValueError('Invalid Pine strategy direction')
                    self.target=float(direction)
                elif fn in ('strategy.close','strategy.close_all'):
                    self.target=0.0
                    self.order_event={'cancel':True}
                elif fn == 'strategy.exit':
                    # Single net position only. from_entry/id are not independent
                    # order books; no qty/qty_percent/trailing/tick orders yet.
                    if len(call.args)>2:
                        raise ValueError('strategy.exit supports id, from_entry, stop and limit only')
                    allowed={'stop','limit','from_entry'}
                    if any(k.arg not in allowed for k in call.keywords):
                        raise ValueError('Unsupported strategy.exit parameter; supported: stop, limit')
                    kw={k.arg:self._value(k.value) for k in call.keywords}
                    stop,limit=kw.get('stop'),kw.get('limit')
                    if stop is None and limit is None:
                        raise ValueError('strategy.exit needs a stop or limit price')
                    if any(type(p) not in (int,float) or not math.isfinite(p) or p<=0
                           for p in (stop,limit) if p is not None):
                        raise ValueError('stop and limit must be positive finite prices')
                    self.order_event={'stop':stop,'limit':limit}
                else: raise ValueError(f'Pine order not supported: {fn}')

    def __call__(self, ctx: dict) -> float:
        self.ctx=ctx
        self.order_event=None
        self.ops=0
        self.bar_index+=1
        self.target=float(ctx.get('target',0))
        self._run(self.body)
        for name, value in self.variables.items():
            h=self.history.setdefault(name,[])
            h.append(value)
            if len(h)>self.history_depth: del h[:-self.history_depth]
        return self.target

    def close(self):
        pass
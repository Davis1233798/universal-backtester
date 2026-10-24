// Node.js JSON-lines strategy: stdout MUST contain exactly one JSON per input line.
// Example config: {"strategy":{"type":"process","command":["node","examples/javascript_strategy.mjs"]}}
import readline from 'node:readline';
for await (const line of readline.createInterface({input: process.stdin})) {
  try {
    const {bars, target} = JSON.parse(line);
    const n = 20;
    const closes = bars.map(b => b.close);
    const avg = closes.length >= n ? closes.slice(-n).reduce((a,b) => a+b,0)/n : Infinity;
    process.stdout.write(JSON.stringify({target: closes.at(-1) > avg ? 1 : 0})+'\n');
  } catch(e) {process.stderr.write(String(e)+'\n');process.exit(1)}
}

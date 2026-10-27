export interface Candle {ts:number;open:number;high:number;low:number;close:number;volume:number;funding_rate?:number;source_bars?:number;n_bars?:number;is_partial?:boolean;last_ts?:number}
export interface EquityPoint {ts:number;equity:number;position?:number;close?:number}
export interface Fill {ts:number;price:number;qty:number;fee:number;reason:string;venue?:string}
export interface CloseTrade {ts:number;entry_ts?:number;entry_price?:number;exit_price?:number;gross_pnl:number;net_pnl:number;r_multiple:number|null;reason:string;qty?:number;venue?:string}
export interface BacktestResult {run_id?:string;metrics:Record<string,number|string|null>;equity:EquityPoint[];equity_preview?:EquityPoint[];fills:Fill[];closed_trades:CloseTrade[];candles_preview?:Candle[];bars:number;warnings?:string[];coverage?:Record<string,unknown>;assumptions?:string[];streaming_preview_only?:boolean}
export interface DataParams {provider:string;exchange:string;symbol:string;timeframe:string;start:string;end:string;market_type:string;include_funding:boolean;allow_partial:boolean;csv_path?:string}
export interface RiskParams {initial_cash:number;fee_bps:number;slippage_bps:number;leverage:number;product_type:string;market:string;r_reference_stop_pct:number|null;force_close:boolean}
export interface StrategyParams {type:string;name?:string;code?:string;options?:Record<string,number>}
export interface BacktestConfig {data:DataParams;risk:RiskParams;strategy:StrategyParams;streaming:boolean;refresh:boolean}
export interface SavedStrategy {id:string;name:string;kind:'pine'|'builtin';code:string;strategy_name?:string;options:Record<string,number>;created_at:string;updated_at:string;revision?:number}
export interface SourceData {providers:string[];strategies:string[];ccxt_exchanges_installed:string[];public_demo:boolean;limitations:string}
export interface Health {ok:boolean;version:string;public_demo:boolean;deployed_commit:string|null}

export class API {
  private bearer: string = '';
  setBearer(value:string){this.bearer=value.trim()}
  clearBearer(){this.bearer=''}
  async request<T>(path:string, init:RequestInit={}):Promise<T>{
    const headers=new Headers(init.headers);
    if(this.bearer) headers.set('Authorization',`Bearer ${this.bearer}`);
    if(init.body && !headers.has('Content-Type'))headers.set('Content-Type','application/json');
    let response:Response;
    const request=()=>fetch(path,{...init,headers,credentials:'omit',cache:'no-store'});
    try{response=await request();}
    catch{
      // Market chart reads can safely retry after a transient cold-start or 4G loss.
      // Do not retry order/backtest/job POSTs that can have side effects.
      if(!init.method||init.method==='GET'||path==='/api/candles/load'){
        await new Promise(resolve=>setTimeout(resolve,1200));
        try{response=await request();}
        catch{throw new Error('網路連接失敗：無法聯繫目前網站的 API，請檢查網路或 Render 服務狀態。')}
      }else{
        throw new Error('網路連接失敗：回測 API 沒有回應；為避免重複提交，沒有自動重送工作。')
      }
    }
    const raw=await response.text();let body:unknown;
    try{body=raw?JSON.parse(raw):null}catch{body=raw}
    if(!response.ok){
      const detail=(body && typeof body==='object' && 'detail' in body)?(body as {detail:unknown}).detail:body;
      const msg=typeof detail==='string'?detail:JSON.stringify(detail||response.statusText);
      throw new Error(`${response.status} · ${msg}`);
    }
    return body as T;
  }
  get<T>(path:string){return this.request<T>(path)}
  post<T>(path:string, data:unknown){return this.request<T>(path,{method:'POST',body:JSON.stringify(data)})}
  put<T>(path:string,data:unknown){return this.request<T>(path,{method:'PUT',body:JSON.stringify(data)})}
  delete<T>(path:string){return this.request<T>(path,{method:'DELETE'})}
  patch<T>(path:string,data:unknown){return this.request<T>(path,{method:'PATCH',body:JSON.stringify(data)})}
}
export const client=new API();
export const fmt=(x:number|null|undefined, digits=2):string=>x==null||!Number.isFinite(x)?'—':new Intl.NumberFormat('zh-TW',{maximumFractionDigits:digits,minimumFractionDigits:digits}).format(x);
export const signed=(x:number|null|undefined,suffix='')=>x==null?'—':`${x>0?'+':''}${fmt(x)}${suffix}`;
export const dateAt=(ms?:number)=>ms?new Date(ms).toISOString().slice(0,16).replace('T',' '):'—';
export const dayOffset=(days:number)=>new Date(Date.now()-days*86400000).toISOString().slice(0,10);
export const samplePine=`//@version=6\nstrategy("EMA Cross Research", overlay=true)\nfast = input.int(9, "Fast")\nslow = input.int(21, "Slow")\nfastMA = ta.ema(close, fast)\nslowMA = ta.ema(close, slow)\nif ta.crossover(fastMA, slowMA)\n    strategy.entry("Long", strategy.long)\nif ta.crossunder(fastMA, slowMA)\n    strategy.close("Long")`;
export const initialConfig:BacktestConfig={
  data:{provider:'ccxt',exchange:'binanceusdm',symbol:'BTC/USDT:USDT',timeframe:'1h',start:dayOffset(45),end:dayOffset(-1),market_type:'swap',include_funding:false,allow_partial:false},
  risk:{initial_cash:10000,fee_bps:6,slippage_bps:2,leverage:1,product_type:'perp',market:'crypto',r_reference_stop_pct:2,force_close:true},
  strategy:{type:'pine',code:samplePine},streaming:false,refresh:false
};
export const marketLines=`ccxt,binanceusdm,BTC/USDT:USDT,5,2\nccxt,bybit,BTC/USDT:USDT,6,2\nhyperliquid,,BTC,4,2`;
export function parseMarkets(text:string){
  const lines=text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  if(!lines.length)throw new Error('至少指定一個市場');
  return lines.map((line,i)=>{
    const p=line.split(',').map(x=>x.trim());
    if(![3,5].includes(p.length)||!p[0]||!p[2])throw new Error(`第 ${i+1} 行格式：provider,exchange,symbol[,fee_bps,slippage_bps]`);
    const risk:Record<string,number>={};
    if(p.length===5){const f=Number(p[3]),s=Number(p[4]);if(!p[3]||!p[4]||!Number.isFinite(f)||!Number.isFinite(s)||f<0||s<0)throw new Error(`第 ${i+1} 行費率或滑價無效`);risk.fee_bps=f;risk.slippage_bps=s;}
    return {data:{provider:p[0],exchange:p[1],symbol:p[2]},risk};
  });
}
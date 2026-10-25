import {useEffect,useMemo,useRef,useState} from 'react';
import {createChart,CrosshairMode,LineStyle,type IChartApi,type ISeriesApi,type UTCTimestamp,type SeriesMarker} from 'lightweight-charts';
import {BarChart3,Activity,Info,RotateCcw} from 'lucide-react';
import type {Candle,EquityPoint,Fill} from './api';
import {fmt} from './api';

type Overlay='ema'|'boll'|'rsi'|'macd';
const time=(ts:number)=>Math.floor(ts/1000) as UTCTimestamp;
const ema=(arr:number[],n:number)=>{const k=2/(n+1),out:number[]=[];arr.forEach((v,i)=>out.push(i===0?v:v*k+out[i-1]*(1-k)));return out};
const sma=(arr:number[],n:number)=>{let sum=0;return arr.map((v,i)=>{sum+=v;if(i>=n)sum-=arr[i-n];return i+1>=n?sum/n:null})};
function rsi(arr:number[],n=14){let gain=0,loss=0;return arr.map((v,i)=>{if(!i)return null;const diff=v-arr[i-1],g=Math.max(0,diff),l=Math.max(0,-diff);gain=i<=n?gain+g:gain*(n-1)/n+g;loss=i<=n?loss+l:loss*(n-1)/n+l;return i<n?null:100-100/(1+(gain/Math.max(loss,1e-12)))})}
const valid=(point: number|null)=>point!==null && Number.isFinite(point);

export function CandleChart({bars,fills=[],label,loading=false,onReload}:{bars:Candle[];fills?:Fill[];label:string;loading?:boolean;onReload?:()=>void}){
 const outer=useRef<HTMLDivElement>(null),chart=useRef<IChartApi|null>(null);
 const [overlays,setOverlays]=useState<Overlay[]>(['ema']);
 const latest=bars.length?bars[bars.length-1]:null;
 const data=useMemo(()=>bars.filter(b=>Number.isFinite(b.open)&&Number.isFinite(b.high)&&Number.isFinite(b.low)&&Number.isFinite(b.close)).sort((a,b)=>a.ts-b.ts).filter((b,i,all)=>i===0||b.ts!==all[i-1].ts),[bars]);
 function toggle(name:Overlay){setOverlays(old=>old.includes(name)?old.filter(x=>x!==name):[...old,name])}
 useEffect(()=>{
   const root=outer.current;if(!root||!data.length)return;
   const instance=createChart(root,{width:Math.max(root.clientWidth,320),height:420,
     layout:{background:{color:'#101927'},textColor:'#8f9db3',fontFamily:'Inter, system-ui, sans-serif',fontSize:11},
     grid:{vertLines:{color:'#1a2736'},horzLines:{color:'#1a2736'}},
     crosshair:{mode:CrosshairMode.Normal},
     rightPriceScale:{borderColor:'#2b384b',scaleMargins:{top:.08,bottom:.24}},
     timeScale:{timeVisible:true,secondsVisible:false,borderColor:'#2b384b',rightOffset:8},
     handleScroll:{mouseWheel:true,pressedMouseMove:true},handleScale:{mouseWheel:true,pinch:true,axisPressedMouseMove:true}
   });chart.current=instance;
   const candles=instance.addCandlestickSeries({upColor:'#24ba98',downColor:'#f36975',wickUpColor:'#24ba98',wickDownColor:'#f36975',borderVisible:false});
   candles.setData(data.map(b=>({time:time(b.ts),open:b.open,high:b.high,low:b.low,close:b.close})));
   const volumes=instance.addHistogramSeries({priceScaleId:'vol',priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false});
   instance.priceScale('vol').applyOptions({scaleMargins:{top:.83,bottom:0}});
   volumes.setData(data.map(b=>({time:time(b.ts),value:b.volume,color:b.close>=b.open?'#135a56':'#602f3b'})));
   const close=data.map(b=>b.close),times=data.map(b=>time(b.ts));
   if(overlays.includes('ema')){
     const fast=instance.addLineSeries({color:'#e4ae57',lineWidth:2,title:'EMA 9',priceLineVisible:false,lastValueVisible:false});
     const slow=instance.addLineSeries({color:'#839ef8',lineWidth:2,title:'EMA 21',priceLineVisible:false,lastValueVisible:false});
     fast.setData(ema(close,9).map((value,i)=>({time:times[i],value})));
     slow.setData(ema(close,21).map((value,i)=>({time:times[i],value})));
   }
   if(overlays.includes('boll')){
     const mean=sma(close,20);
     const upper=instance.addLineSeries({color:'#a88ceb',lineWidth:1,lineStyle:LineStyle.Dashed,priceLineVisible:false,lastValueVisible:false});
     const lower=instance.addLineSeries({color:'#a88ceb',lineWidth:1,lineStyle:LineStyle.Dashed,priceLineVisible:false,lastValueVisible:false});
     const up: {time:UTCTimestamp;value:number}[]=[],down:{time:UTCTimestamp;value:number}[]=[];
     mean.forEach((m,i)=>{if(m!==null){const part=close.slice(i-19,i+1),sd=Math.sqrt(part.reduce((s,v)=>s+(v-m)**2,0)/20);up.push({time:times[i],value:m+2*sd});down.push({time:times[i],value:m-2*sd})}});
     upper.setData(up);lower.setData(down);
   }
   if(overlays.includes('rsi')){
     const values=rsi(close),line=instance.addLineSeries({color:'#b48ce9',lineWidth:2,priceScaleId:'rsi',priceLineVisible:false,lastValueVisible:false,title:'RSI'});
     instance.priceScale('rsi').applyOptions({scaleMargins:{top:.71,bottom:.13}});
     line.setData(values.flatMap((v,i)=>valid(v)?[{time:times[i],value:v as number}]:[]));
   }
   if(overlays.includes('macd')){
     const e12=ema(close,12),e26=ema(close,26),macd=e12.map((v,i)=>v-e26[i]),sig=ema(macd,9);
     const hist=instance.addHistogramSeries({priceScaleId:'macd',lastValueVisible:false,priceLineVisible:false});
     instance.priceScale('macd').applyOptions({scaleMargins:{top:.75,bottom:.02}});
     hist.setData(macd.map((v,i)=>({time:times[i],value:v-sig[i],color:v>=sig[i]?'#299c83':'#bc5864'})));
   }
   if(fills.length){
     const markers:SeriesMarker<UTCTimestamp>[]=fills.filter(f=>data.some(b=>b.ts===f.ts))
       .map(f=>({time:time(f.ts),position:f.qty>0?'belowBar':'aboveBar',shape:f.qty>0?'arrowUp':'arrowDown',color:f.qty>0?'#24ba98':'#f36975',text:f.qty>0?'B':'S'}))
       .sort((a,b)=>(a.time as number)-(b.time as number));
     candles.setMarkers(markers);
   }
   instance.timeScale().fitContent();
   const observer=new ResizeObserver(()=>instance.applyOptions({width:Math.max(root.clientWidth,320)}));observer.observe(root);
   return ()=>{observer.disconnect();instance.remove();if(chart.current===instance)chart.current=null};
 },[data,overlays,fills]);
 return <section className="panel chart-panel">
   <div className="panel-head chart-title"><div><div className="eyebrow">市場行情 / MARKET CHART</div><h2>{label}</h2></div>
     <div className="toolbar" aria-label="技術指標開關">{(['ema','boll','rsi','macd'] as Overlay[]).map(x=><button key={x} type="button" className={'pill-button '+(overlays.includes(x)?'on':'')} onClick={()=>toggle(x)} aria-pressed={overlays.includes(x)}>{x.toUpperCase()}</button>)}
       {onReload&&<button className="icon-button" type="button" aria-label="重新載入行情" onClick={onReload}><RotateCcw size={16}/></button>}
     </div>
   </div>
   {latest&&<div className="price-strip"><strong>{fmt(latest.close,4)}</strong><span>O {fmt(latest.open,4)}</span><span>H {fmt(latest.high,4)}</span><span>L {fmt(latest.low,4)}</span><span>V {fmt(latest.volume,1)}</span></div>}
   {data.length?<div className="chart-canvas" ref={outer} aria-label={`顯示 ${data.length} 根歷史 K 線`} />:
     <div className="chart-empty"><BarChart3 size={36}/><strong>{loading?'正在載入行情':'歷史 K 線尚未載入'}</strong><p>執行回測或查詢市場行情後，這裡將顯示可縮放的 K 線、成交量與技術指標。</p></div>}
   <div className="chart-foot"><Info size={13}/> 前端技術指標僅供圖表分析；策略績效使用後端完整原始 K 線計算。<span>{data.length?`顯示 ${data.length.toLocaleString()} 點`:''}</span></div>
 </section>
}

export function EquityChart({points}:{points:EquityPoint[]}){
 const root=useRef<HTMLDivElement>(null);
 useEffect(()=>{const container=root.current;if(!container||points.length<2)return;
  const c=createChart(container,{width:Math.max(300,container.clientWidth),height:240,
   layout:{background:{color:'#111a28'},textColor:'#90a1b9'},grid:{horzLines:{color:'#1c2a39'},vertLines:{color:'#1c2a39'}},
   timeScale:{borderVisible:false,timeVisible:true},rightPriceScale:{borderVisible:false}});
  const series=c.addAreaSeries({topColor:'rgba(41,190,154,.28)',bottomColor:'rgba(41,190,154,0)',lineColor:'#29be9a',lineWidth:2,priceLineVisible:false});
  const normalized=[...points].filter(x=>Number.isFinite(x.equity)).sort((a,b)=>a.ts-b.ts).filter((p,i,arr)=>i===0||p.ts!==arr[i-1].ts);
  series.setData(normalized.map(p=>({time:time(p.ts),value:p.equity})));
  c.timeScale().fitContent();const observer=new ResizeObserver(()=>c.applyOptions({width:Math.max(300,container.clientWidth)}));observer.observe(container);
  return()=>{observer.disconnect();c.remove()};
 },[points]);
 return <section className="panel"><div className="panel-head"><div><div className="eyebrow">EQUITY CURVE</div><h2>資產權益走勢</h2></div><Activity size={18} className="muted"/></div>
 {points.length>=2?<div ref={root} className="equity-canvas"/>:<div className="small-empty">執行回測後顯示資金曲線</div>}
 </section>
}
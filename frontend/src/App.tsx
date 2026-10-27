interface MarketChartResponse {
 candles:Candle[];
 represented_bars:number;
 warnings:string[];
 provider:string;exchange:string;symbol:string;timeframe:string;
 server_time_ms:number;
 fetched_at_ms:number|null;
 last_price_ts:number|null;
 last_completed_ts:number|null;
 is_live:boolean;partial_candle:boolean;
 live_warning:string|null;
 exact_timeframe:boolean;
 native_interval_ms:number;
 view_start_ms:number;
 view_end_ms:number;
}
import {useCallback,useEffect,useMemo,useRef,useState,type ChangeEvent,type FormEvent,type ReactNode} from 'react';
import {
 Activity,ArrowDownRight,ArrowLeftRight,ArrowRight,ArrowUpRight,BarChart3,BarChartBig,BookOpen,
 Calendar,CheckCircle2,ChevronDown,ChevronLeft,ChevronRight,Clock,Cloud,Code2,Copy,Download,
 ExternalLink,FileCode2,FileUp,Filter,History,Layers3,LayoutDashboard,LockKeyhole,Menu,
 Play,Plus,RefreshCw,Save,Search,Settings2,ShieldCheck,SlidersHorizontal,Target,Trash2,
 TrendingUp,Wallet,Wifi,WifiOff,X,Zap,AlertTriangle,NotebookTabs,SquareChartGantt
} from 'lucide-react';
import {CandleChart,EquityChart} from './Charts';
import {client,dateAt,dayOffset,fmt,initialConfig,marketLines,parseMarkets,samplePine,signed,
 type BacktestConfig,type BacktestResult,type Candle,type SavedStrategy,type SourceData,type Health} from './api';

type View='terminal'|'strategies'|'batch'|'analytics'|'history'|'jobs';
const NAV:{id:View;name:string;desc:string;icon:typeof Activity}[]=[
 {id:'terminal',name:'交易研究台',desc:'K 線與策略回測',icon:LayoutDashboard},
 {id:'strategies',name:'策略工廠',desc:'編輯與版本管理',icon:Code2},
 {id:'batch',name:'多市場回測',desc:'交易所與資金組合',icon:Layers3},
 {id:'analytics',name:'績效分析',desc:'風險與交易明細',icon:BarChart3},
 {id:'history',name:'回測紀錄',desc:'歷史結果與比較',icon:History},
 {id:'jobs',name:'每日任務',desc:'排程與執行狀態',icon:Clock}
];
const METRICS:{key:string;label:string;suffix?:string;description:string}[]=[
 {key:'net_profit',label:'淨利',description:'最終權益減去初始資金'},
 {key:'return_pct',label:'總報酬率',suffix:'%',description:'回測期間的累積報酬'},
 {key:'max_drawdown_pct',label:'最大回撤',suffix:'%',description:'資金曲線從峰值至谷底的最大跌幅'},
 {key:'win_rate_pct',label:'勝率',suffix:'%',description:'已平倉的淨獲利交易佔比'},
 {key:'profit_factor',label:'營利因子',description:'淨獲利金額總和 ÷ 淨虧損絕對值總和'},
 {key:'average_r',label:'平均 R',suffix:' R',description:'每筆淨損益 ÷ 設定的 1R 參考風險，再取平均'},
 {key:'sharpe',label:'Sharpe Ratio',description:'風險調整後的年化報酬'},
 {key:'sortino',label:'Sortino Ratio',description:'只將下行波動納入風險衡量'},
 {key:'calmar',label:'Calmar Ratio',description:'年化報酬對最大回撤'},
 {key:'average_trade_net',label:'平均每筆淨損益',description:'已扣除交易成本與資金費'},
 {key:'closed_trades',label:'平倉交易數',description:'部分平倉各計為一筆'},
 {key:'fees_paid',label:'支付手續費',description:'所有成交手續費'}
];
const cloneConfig=():BacktestConfig=>structuredClone(initialConfig);
function Badge({children,tone='muted'}:{children:ReactNode;tone?:'muted'|'good'|'warn'|'bad'|'blue'}){return <span className={'badge badge-'+tone}>{children}</span>}
function Loading(){return <span className="spinner" aria-hidden="true"/>}
function Message({tone='warn',children}:{tone?:'warn'|'bad'|'good';children:ReactNode}){return <div className={'message message-'+tone}>{tone==='bad'?<AlertTriangle size={16}/>:tone==='good'?<CheckCircle2 size={16}/>:<ShieldCheck size={16}/>}<span>{children}</span></div>}
function NumField({label,value,onChange,step='any',min,help}:{label:string;value:number|string|null;onChange:(v:string)=>void;step?:string;min?:number;help?:string}){return <label className="field"><span>{label}</span><input type="number" value={value??''} step={step} min={min} onChange={e=>onChange(e.target.value)}/>{help&&<small>{help}</small>}</label>}
function SelectField({label,value,onChange,children}:{label:string;value:string;onChange:(s:string)=>void;children:ReactNode}){return <label className="field"><span>{label}</span><select value={value} onChange={e=>onChange(e.target.value)}>{children}</select></label>}
function MetricCard({metric,value}:{metric:typeof METRICS[number];value:unknown}){
 const v=typeof value==='number'?`${fmt(value,metric.key==='closed_trades'?0:2)}${metric.suffix||''}`:'—';
 const negative=typeof value==='number'&&['net_profit','return_pct'].includes(metric.key)&&value<0;
 return <div className="metric-card" title={metric.description}><span>{metric.label}</span><strong className={negative?'negative':metric.key==='net_profit'&&typeof value==='number'&&value>0?'positive':''}>{v}</strong></div>
}
function downloadJSON(value:unknown,filename:string){const a=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));a.href=url;a.download=filename;a.click();URL.revokeObjectURL(url)}
function PageTitle({kicker,title,sub,actions}:{kicker:string;title:string;sub:string;actions?:ReactNode}){return <div className="page-title"><div><div className="eyebrow">{kicker}</div><h1>{title}</h1><p>{sub}</p></div><div className="title-actions">{actions}</div></div>}
const empty=(title:string,sub:string,icon:ReactNode)=><div className="empty-state"><span className="empty-icon">{icon}</span><h3>{title}</h3><p>{sub}</p></div>;

export default function App(){
 const [view,setView]=useState<View>('terminal');
 const [mobileMenu,setMobileMenu]=useState(false);
 const [health,setHealth]=useState<Health|null>(null);
 const [sources,setSources]=useState<SourceData|null>(null);
 const [token,setToken]=useState('');
 const [authError,setAuthError]=useState('');
 const [config,setConfig]=useState<BacktestConfig>(cloneConfig);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [result,setResult]=useState<BacktestResult|null>(null);
 const [candles,setCandles]=useState<Candle[]>([]);
 const [chartInfo,setChartInfo]=useState<MarketChartResponse|null>(null);
 const [chartPageEnd,setChartPageEnd]=useState<number|null>(null);
 const [followLive,setFollowLive]=useState(true);
 const [chartBusy,setChartBusy]=useState(false),[chartError,setChartError]=useState('');
 const chartRequest=useRef(0);
 const [marketQuery,setMarketQuery]=useState(''),[marketMatches,setMarketMatches]=useState<Array<{symbol:string;name?:string;base?:string;exchange?:string}>>([]);
 const [marketBusy,setMarketBusy]=useState(false);
 const [runs,setRuns]=useState<Array<Record<string,unknown>>>([]);
 const [strategies,setStrategies]=useState<SavedStrategy[]>([]);
 const [selectedStrategy,setSelectedStrategy]=useState<string>('');
 const [strategyName,setStrategyName]=useState('EMA Cross Research');
 const [strategiesBusy,setStrategiesBusy]=useState(false);
 const [aiPrompt,setAiPrompt]=useState('');
 const [aiBusy,setAiBusy]=useState(false);
 const [strategyRevisions,setStrategyRevisions]=useState<Array<Record<string,unknown>>>([]);
 const [revisionFor,setRevisionFor]=useState('');
 const [batchText,setBatchText]=useState(marketLines),[batchWorkers,setBatchWorkers]=useState(3);
 const [batchResults,setBatchResults]=useState<Array<Record<string,unknown>>>([]);
 const [portfolioResult,setPortfolioResult]=useState<Record<string,unknown>|null>(null);
 const [entryBps,setEntryBps]=useState(25),[exitBps,setExitBps]=useState(5),[gross,setGross]=useState(.8);
 const [jobs,setJobs]=useState<Array<Record<string,unknown>>>([]);
 const [historySelected,setHistorySelected]=useState('');
 const [indicatorTab,setIndicatorTab]=useState<'trades'|'fills'|'warnings'>('trades');
 const [expandEditor,setExpandEditor]=useState(true);
 const fileInput=useRef<HTMLInputElement>(null);
 const isDemo=health?.public_demo===true;
 const isAuthed=!!sources;
 const isPrivate=isAuthed && !isDemo;
 const updateData=(patch:Partial<BacktestConfig['data']>)=>{
  setChartPageEnd(null);setChartInfo(null);
  setConfig(c=>({...c,data:{...c.data,...patch}}));
};
 const updateRisk=(patch:Partial<BacktestConfig['risk']>)=>setConfig(c=>({...c,risk:{...c.risk,...patch}}));
 const updateStrategy=(patch:Partial<BacktestConfig['strategy']>)=>setConfig(c=>({...c,strategy:{...c.strategy,...patch}}));

 useEffect(()=>{
   client.get<Health>('/api/health').then(async h=>{
     setHealth(h);
     if(h.public_demo){
       const source=await client.get<SourceData>('/api/sources');setSources(source);
       setConfig(prev=>({...prev,data:{...prev.data,provider:'demo',symbol:'SYNTHETIC',exchange:''}}));
     }
   }).catch(e=>setAuthError(String(e)));
 },[]);
 const refreshLibrary=useCallback(async()=>{
   if(health?.public_demo)return;
   const [s,r]=await Promise.all([client.get<SavedStrategy[]>('/api/strategies'),client.get<Array<Record<string,unknown>>>('/api/backtests?limit=40')]);
   setStrategies(Array.isArray(s)?s:[]);setRuns(Array.isArray(r)?r:[]);
 },[health?.public_demo]);
 const refreshJobs=useCallback(async()=>{if(isPrivate)setJobs(await client.get<Array<Record<string,unknown>>>('/api/jobs'));},[isPrivate]);
 useEffect(()=>{if(isPrivate)refreshLibrary().catch(()=>{});},[isPrivate,refreshLibrary]);
 useEffect(()=>{if(isPrivate&&view==='jobs')refreshJobs().catch(e=>setError(e.message));},[view,isPrivate,refreshJobs]);
 async function unlock(e:FormEvent){e.preventDefault();setAuthError('');client.setBearer(token);
  try{const s=await client.get<SourceData>('/api/sources');setSources(s);
    setConfig(prev=>prev.data.provider==='demo'?{...prev,data:{...prev.data,
      provider:'ccxt',exchange:'binanceusdm',symbol:'BTC/USDT:USDT'}}:prev);
    setNotice('已連線正式行情服務。可搜尋任意上市商品，或使用快捷市場。');setToken('');}
  catch(e){setAuthError((e as Error).message);client.clearBearer();}
 }
 function logout(){chartRequest.current+=1;client.clearBearer();setSources(null);setResult(null);setCandles([]);setStrategies([]);setRuns([]);setNotice('已清除本頁授權');}
 async function loadChart(cfg=config, refresh=false, quiet=false, viewEnd=chartPageEnd){
  if(!isPrivate || cfg.data.provider==='demo')return;
  const request=++chartRequest.current;
  if(!quiet){setChartBusy(true);setChartError('');}
  try{
   // Always extend the live chart to tomorrow's UTC midnight.
   // Historical backtest start/end remain unchanged; user-selected past
   // chart dates explicitly turn this off.
   const liveView=followLive&&viewEnd===null&&['ccxt','hyperliquid'].includes(cfg.data.provider);
   const endUtc=new Date(Date.now()+86400000).toISOString().slice(0,10);
   const chartData=liveView?{...cfg.data,end:endUtc}:cfg.data;
   const response=await client.post<MarketChartResponse>('/api/candles/load',{
    data:chartData,refresh,max_points:1500,view_end_ms:viewEnd
   });
   if(request!==chartRequest.current)return;
   if(!response.candles?.length)throw new Error('此商品沒有可用的原始 K 線');
   setCandles(response.candles);
   setChartInfo(response);
   setChartError('');
   if(response.warnings?.length)setNotice('行情來源提醒：'+response.warnings.join('；'));
  }catch(e){
   if(request===chartRequest.current)setChartError((e as Error).message);
  }finally{
   if(request===chartRequest.current)setChartBusy(false);
  }
 }
 useEffect(()=>{
  if(!isPrivate||config.data.provider==='demo')return;
  const t=setTimeout(()=>{void loadChart(config,false,false,chartPageEnd)},450);
  return ()=>{clearTimeout(t);chartRequest.current+=1};
 },[isPrivate,config.data.provider,config.data.exchange,config.data.symbol,
    config.data.market_type,config.data.timeframe,config.data.start,config.data.end,
    config.data.include_funding,chartPageEnd,followLive]);
 // Follow the exchange's evolving OHLCV candle; no full-history refetch.
 useEffect(()=>{
  if(!isPrivate||chartPageEnd!==null||
      !['ccxt','hyperliquid'].includes(config.data.provider))return;
  if(!followLive)return;
  const poll=()=>{
    if(document.visibilityState==='visible'&&!chartBusy){
      void loadChart(config,false,true,null);
    }
  };
  const timer=window.setInterval(poll,30000);
  document.addEventListener('visibilitychange',poll);
  return ()=>{window.clearInterval(timer);document.removeEventListener('visibilitychange',poll)};
 },[isPrivate,chartPageEnd,config,chartBusy,followLive]);
 async function runBacktest(){setBusy(true);setError('');setNotice('');
  try{
   const cfg=structuredClone(config);
   if(isDemo){cfg.data.provider='demo';cfg.data.exchange='';cfg.data.symbol='SYNTHETIC';cfg.data.include_funding=false;cfg.streaming=false;cfg.refresh=false;}
   if(cfg.strategy.type==='pine' && !cfg.strategy.code?.trim())throw new Error('請先輸入 Pine Script 策略');
   const output=await client.post<BacktestResult>('/api/backtests',cfg);
   setResult(output);if(isDemo)setCandles(output.candles_preview||[]);setView('terminal');
   setNotice(`回測完成 · ${output.bars.toLocaleString()} 根原始 K 線${isDemo?' · 合成示範行情':''}`);
   if(!isDemo){void loadChart(cfg);void refreshLibrary()}
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 async function lookupMarkets(){setMarketBusy(true);setError('');
  try{if(isDemo)throw new Error('公開示範沒有真實交易所市場搜尋');
    const q=new URLSearchParams({provider:config.data.provider,exchange:config.data.exchange,market_type:config.data.market_type,q:marketQuery.trim()||(config.data.provider==='hyperliquid'?'BTC':
      config.data.provider==='yfinance'?'AAPL':'USDT'),limit:'60'});
    const out=await client.get<{items:typeof marketMatches;matched_count:number}>('/api/markets?'+q.toString());setMarketMatches(out.items||[]);
    setNotice(`找到 ${out.matched_count||0} 筆市場，以下顯示最多 60 筆`);
  }catch(e){setError((e as Error).message)}finally{setMarketBusy(false)}
 }
 function loadSaved(s:SavedStrategy){setSelectedStrategy(s.id);setStrategyName(s.name);setConfig(c=>({...c,strategy:s.kind==='pine'?{type:'pine',code:s.code}:{type:'builtin',name:s.strategy_name||'sma_cross',options:s.options||{fast:10,slow:30}}}));setView('terminal');setExpandEditor(true);setNotice(`已載入策略：${s.name}`)}
 async function saveStrategy(){if(!isPrivate){setError('公開 Demo 不會儲存策略。請使用私人部署。');return;}
  setStrategiesBusy(true);setError('');try{
    const data={name:strategyName,kind:config.strategy.type,code:config.strategy.code||'',strategy_name:config.strategy.name||'',options:config.strategy.options||{}};
    const s=selectedStrategy?await client.put<SavedStrategy>('/api/strategies/'+selectedStrategy,data):await client.post<SavedStrategy>('/api/strategies',data);
    setSelectedStrategy(s.id);await refreshLibrary();setNotice(`已儲存策略「${s.name}」版本 ${s.revision||1}`);
  }catch(e){setError((e as Error).message)}finally{setStrategiesBusy(false)}
 }
 async function showRevisions(id:string){
  try{const list=await client.get<Array<Record<string,unknown>>>(`/api/strategies/${id}/revisions`);setStrategyRevisions(list);setRevisionFor(id)}
  catch(e){setError((e as Error).message)}
 }
 async function restoreStrategy(id:string,revision:number){
  try{const updated=await client.post<SavedStrategy>(`/api/strategies/${id}/restore/${revision}`,{});
   await refreshLibrary();await showRevisions(id);setNotice(`已還原為第 ${revision} 版，並建立新版本 v${updated.revision}`);}
  catch(e){setError((e as Error).message)}
 }
 async function generateAI(){
  if(!isPrivate){setError('AI 策略生成必須在私人部署使用');return}
  if(aiPrompt.trim().length<12){setError('請輸入至少 12 個字元的策略描述');return}
  setAiBusy(true);setError('');
  try{
    const output=await client.post<{code:string;model:string;notice:string}>('/api/strategies/generate',{description:aiPrompt});
    setStrategyName('AI 策略草稿');
    setSelectedStrategy('');
    updateStrategy({type:'pine',code:output.code});
    setView('terminal');
    setExpandEditor(true);
    setNotice('AI 已生成 Pine 草稿，通過相容子集解析，但尚未執行或儲存。請先審閱程式。');
  }catch(e){setError((e as Error).message)}
  finally{setAiBusy(false)}
 }
 async function removeStrategy(id:string){if(!confirm('確定刪除這個策略及版本紀錄？'))return;
  try{await client.delete('/api/strategies/'+id);if(selectedStrategy===id)setSelectedStrategy('');await refreshLibrary();setNotice('已刪除策略');}
  catch(e){setError((e as Error).message)}
 }
 async function runBatch(shared=false){setBusy(true);setError('');setNotice('');
  try{
    if(!isPrivate)throw new Error('跨市場回測必須在私人部署中使用');
    const markets=parseMarkets(batchText);
    if(shared){if(markets.length<2)throw new Error('共享資金模式需要至少兩個市場');
      const payload={venues:markets.map((m,i)=>({id:`venue_${i+1}`,data:{...config.data,...m.data},risk:{...config.risk,...m.risk,product_type:'perp'}})),
        portfolio:{initial_cash:config.risk.initial_cash,gross_notional_fraction:gross},
        strategy:{type:'spread',entry_bps:entryBps,exit_bps:exitBps}};
      const output=await client.post<Record<string,unknown>>('/api/portfolio/backtests',payload);setPortfolioResult(output);setNotice('共同資金價差回測完成，請注意模型未包含跨平台轉帳延遲及 Gas 費');}
    else{const payload={strategy:config.strategy,risk:config.risk,markets:markets.map(m=>({data:{...config.data,...m.data},risk:m.risk})),workers:batchWorkers,streaming:config.streaming,refresh:config.refresh,chart_points:1000};
      const out=await client.post<{results:Array<Record<string,unknown>>;successful:number;failed:number}>('/api/backtests/batch',payload);
      setBatchResults(out.results||[]);setNotice(`批次完成：成功 ${out.successful}、失敗 ${out.failed}`);}
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 async function loadRun(id:string){setBusy(true);setError('');
  try{const item=await client.get<{result:BacktestResult;config?:BacktestConfig}>('/api/backtests/'+encodeURIComponent(id));
    setResult(item.result);setCandles(item.result.candles_preview||[]);if(item.config)setConfig(item.config);
    setHistorySelected(id);setView('analytics');setNotice(`已載入回測 ${id.slice(0,8)}`);
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 async function createJob(){setBusy(true);setError('');
  try{const item=await client.post<{job_id:string}>('/api/jobs',config);await refreshJobs();setNotice(`已建立每日回測任務 ${item.job_id.slice(0,8)}（須啟動 scheduler）`);}
  catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 async function toggleJob(id:string,active:boolean){try{await client.request(`/api/jobs/${id}?active=${active}`,{method:'PATCH'});await refreshJobs();}catch(e){setError((e as Error).message)}}
 const page= NAV.find(x=>x.id===view)!;
 return <div className="app-shell">
   <aside className={'sidebar '+(mobileMenu?'open':'')}>
     <div className="brand"><div className="brand-glyph"><Activity size={22}/></div><div><strong>UNIVERSAL<span>BT</span></strong><small>QUANT RESEARCH TERMINAL</small></div></div>
     <div className="nav-caption">WORKSPACE <span>01</span></div>
     <nav aria-label="主選單">{NAV.map(item=>{const Icon=item.icon;return <button key={item.id} type="button" className={'nav-link '+(view===item.id?'active':'')} onClick={()=>{setView(item.id);setMobileMenu(false);setError('')}}><Icon size={19}/><span><strong>{item.name}</strong><small>{item.desc}</small></span>{view===item.id&&<span className="active-dot"/>}</button>})}</nav>
     <div className="sidebar-bottom"><div className="research-note"><ShieldCheck size={18}/><div><strong>研究模式</strong><p>非交易建議 · 不會自動下單</p></div></div>
       <div className="sidebar-version"><span className="live-dot"/>{health?.ok?'API ONLINE':'API OFFLINE'}<small>v1.0 UI</small></div>
     </div>
   </aside>
   {mobileMenu&&<div className="mobile-overlay" onClick={()=>setMobileMenu(false)}/>}
   <div className="main-column"><header className="topbar">
     <div className="topbar-left"><button className="mobile-menu icon-button" aria-label="開啟選單" onClick={()=>setMobileMenu(x=>!x)}><Menu size={20}/></button><span className="crumb">WORKSPACE</span><ChevronRight size={14}/><strong>{page.name}</strong><Badge tone={isDemo?'warn':isPrivate?'good':'bad'}>{isDemo?'SYNTHETIC DEMO':isPrivate?'PRIVATE SESSION':'LOCKED'}</Badge></div>
     <div className="topbar-right"><span className="topbar-clock"><Clock size={14}/> {new Date().toISOString().slice(0,10)} UTC</span>
       {health?.deployed_commit&&<span className="commit-id">{health.deployed_commit.slice(0,7)}</span>}
       {isPrivate?<button className="quiet-button" onClick={logout}><LockKeyhole size={15}/> 登出</button>:<span className="connection"><span className="live-dot"/>{health?.ok?'Connected':'Connecting'}</span>}</div>
   </header>
   <main className="content">
    {!health&&!authError&&<div className="boot"><Loading/><p>正在連線到回測服務…</p></div>}
    {health&&!isAuthed&&!isDemo&&<section className="access-layout"><div className="access-copy"><Badge tone="blue">PROFESSIONAL RESEARCH</Badge><h1>每一筆交易，<br/><em>都應有數據依據。</em></h1><p>研究全球加密資產與股票、回放完整可取得的歷史資料、建立自己的 Pine 策略並比較不同交易所的風險與報酬。</p><div className="access-points"><span><BarChart3 size={18}/>互動行情與指標</span><span><Code2 size={18}/>策略研究工作區</span><span><ShieldCheck size={18}/>受保護的私有 API</span></div></div>
     <form className="panel auth-card" onSubmit={unlock}><div className="auth-symbol"><LockKeyhole size={23}/></div><h2>私人工作區存取</h2><p>正式版回測、行情與工作排程需要 API 授權。Token 僅保留在目前分頁記憶體中。</p><label className="field"><span>API 存取 Token</span><input type="password" autoComplete="off" value={token} onChange={e=>setToken(e.target.value)} placeholder="輸入伺服器設定的 UBT_API_TOKEN"/></label><button className="primary-button wide" type="submit" disabled={!token.trim()}><ShieldCheck size={18}/> 驗證並進入工作區 <ArrowRight size={17}/></button>{authError&&<Message tone="bad">{authError}</Message>}<small>未配置 Token 的私人 API 預設鎖定，不提供匿名存取。</small></form>
    </section>}
    {health&&isAuthed&&<>
      {isDemo&&<div className="demo-banner"><AlertTriangle size={18}/><div><strong>公開版使用合成行情</strong><span>所有價格與績效僅供流程測試，並非真實交易所數據。市場搜尋、儲存、批次及排程需要私人部署。</span></div></div>}
      {error&&<Message tone="bad"><strong>操作失敗：</strong> {error}<button onClick={()=>setError('')} className="dismiss" aria-label="關閉錯誤"><X size={14}/></button></Message>}
      {notice&&<Message tone="good">{notice}<button onClick={()=>setNotice('')} className="dismiss" aria-label="關閉提示"><X size={14}/></button></Message>}
      {view==='terminal'&&<>
        <PageTitle kicker="RESEARCH WORKSPACE / 01" title="策略回測工作台" sub="串接行情、編輯策略、執行回測，再用完整交易指標解讀績效。"
          actions={<><button className="outline-button" onClick={()=>setView('strategies')}><BookOpen size={16}/> 策略工廠</button><button className="primary-button" onClick={runBacktest} disabled={busy}>{busy?<Loading/>:<Play size={16}/>} 執行回測</button></>}/>
        <div className="workspace-grid"><div className="workspace-main">
          <div className="market-strip"><div className="market-asset"><div className="asset-icon">₿</div><div><strong>{config.data.symbol||'BTC/USDT'}</strong><small>{config.data.provider.toUpperCase()} {config.data.exchange&&'· '+config.data.exchange}</small></div></div>
          <div className="market-actions"><span className="muted">K 線週期</span>{['15m','1h','4h','1d'].map(t=><button key={t} className={'time-chip '+(t===config.data.timeframe?'active':'')} onClick={()=>updateData({timeframe:t})}>{t}</button>)}<span className="splitter"/><button className="quiet-button" onClick={()=>loadChart(config,true,false,chartPageEnd)} disabled={busy||chartBusy||isDemo}>
{chartBusy?<Loading/>:<RefreshCw size={14}/>} 重新整理行情</button></div></div>
          {isPrivate&&<div className="market-switcher">
            <div className="market-switcher-top">
             <label className="field"><span>搜尋交易所所有上市商品</span><div className="input-row">
               <input aria-label="市場商品搜尋" type="search" value={marketQuery}
                 onChange={e=>setMarketQuery(e.target.value)}
                 onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();void lookupMarkets()}}}
                 placeholder={config.data.provider==='yfinance'?'AAPL、NVDA、2330.TW':'ETH、SOL、XRP 或商品代碼'}/>
               <button type="button" className="outline-button" disabled={marketBusy}
                 onClick={lookupMarkets}>{marketBusy?<Loading/>:<Search size={16}/>} 搜尋</button>
             </div></label>
             <span className="market-hint">從交易所即時商品目錄搜尋，沒有 BTC 單幣限制。</span>
            </div>
            <div className="market-venues" aria-label="切換真實行情供應商與交易所">
              {([
                {name:'Binance',provider:'ccxt',exchange:'binanceusdm'},
                {name:'Bybit',provider:'ccxt',exchange:'bybit'},
                {name:'OKX',provider:'ccxt',exchange:'okx'},
                {name:'Hyperliquid',provider:'hyperliquid',exchange:''},
                {name:'全球股票',provider:'yfinance',exchange:''}
              ] as const).map(venue=><button key={venue.name} type="button"
                className={'time-chip '+(config.data.provider===venue.provider &&
                  config.data.exchange===venue.exchange?'active':'')}
                onClick={()=>{
                  const stock=venue.provider==='yfinance',dex=venue.provider==='hyperliquid';
                  const base=(config.data.symbol.split(/[/:]/)[0]||'BTC').toUpperCase();
                  const nextBase=['BTC','ETH','SOL','XRP','DOGE','ADA','BNB','LINK','LTC','AVAX'].includes(base)?base:'BTC';
                  updateData({provider:venue.provider,exchange:venue.exchange,
                    symbol:stock?'AAPL':dex?nextBase:nextBase+'/USDT:USDT',
                    market_type:stock?'spot':'swap',include_funding:false});
                  updateRisk({product_type:stock?'equity':'perp',market:stock?'stock':'crypto',
                    leverage:stock?1:config.risk.leverage});
                  setMarketMatches([]);setMarketQuery('');
                }}>{venue.name}</button>)}
            </div>
            <div className="market-quick">
             {(config.data.provider==='yfinance'
               ?['AAPL','NVDA','TSLA','MSFT','2330.TW']
               :config.data.provider==='hyperliquid'
                ?['BTC','ETH','SOL','XRP','DOGE','HYPE']
                :['BTC','ETH','SOL','XRP','DOGE','BNB','ADA','AVAX','LINK','LTC']
               ).map(base=><button type="button" key={base} className="time-chip"
                 onClick={()=>{const symbol=config.data.provider==='yfinance'||config.data.provider==='hyperliquid'
                   ?base:base+'/USDT'+(config.data.market_type==='spot'?'':':USDT');
                   updateData({symbol});setMarketQuery(base);setMarketMatches([])}}>
                 {base}</button>)}
            </div>
            {marketMatches.length>0&&<div className="market-search-results" role="listbox" aria-label="已搜尋到的交易商品">
              {marketMatches.map((m,i)=><button type="button" role="option"
                aria-selected={m.symbol===config.data.symbol} key={m.symbol+'-'+i}
                onClick={()=>{updateData({symbol:m.symbol});setMarketMatches([]);setMarketQuery(m.symbol)}}>
                <strong>{m.symbol}</strong><span>{m.name||m.base||m.exchange||'可交易商品'}</span>
              </button>)}
             </div>}
          </div>}
          {isPrivate&&<div className="market-sync">
            <span className={'sync-light '+(chartInfo?.is_live&&!chartError?'on':'')}></span>
            <label className="follow-live"><input type="checkbox" checked={followLive}
              onChange={e=>{setFollowLive(e.target.checked);setChartPageEnd(null)}}/>
              跟隨即時 K 線</label>
            <span>{chartInfo?.is_live?'市場 K 線同步中（每 30 秒重新查詢）':
              chartPageEnd!==null?'歷史時間範圍 · 暫停即時同步':
              '尚未取得即時行情'}</span>
            {chartInfo?.fetched_at_ms&&<span>最近請求：{new Date(chartInfo.fetched_at_ms).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false})}</span>}
            {chartInfo?.last_price_ts&&<span>K 線起始時間：{new Date(chartInfo.last_price_ts).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false})}（台北）</span>}
            <span>{chartInfo?.partial_candle?'含尚未收盤 K 線':'最後一根為已收盤 K 線'}</span>
            {chartInfo?.live_warning&&<span className="market-sync-warning">{chartInfo.live_warning}</span>}
            {chartInfo&&!chartInfo.exact_timeframe&&<span className="market-sync-warning">顯示為聚合 K 線，非原生週期</span>}
            <div className="sync-pager">
              <button type="button" className="outline-button slim" disabled={!candles.length||chartBusy||
                !chartInfo||chartInfo.view_start_ms<=new Date(config.data.start).getTime()}
                onClick={()=>setChartPageEnd(candles[0].ts)}>← 更早 K 線</button>
              <button type="button" className="outline-button slim" disabled={chartPageEnd===null}
                onClick={()=>setChartPageEnd(null)}>最新 K 線 →</button>
            </div>
          </div>}
          {chartError&&<Message tone="bad"><strong>行情載入失敗：</strong> {chartError}<button className="outline-button slim"
            onClick={()=>loadChart(config,true,false,chartPageEnd)}>重試抓取真實行情</button></Message>}
          <CandleChart bars={candles} fills={result?.fills||[]} label={config.data.symbol}
            loading={busy||chartBusy} onReload={isPrivate?()=>loadChart(config,true,false,chartPageEnd):undefined}/>
          <div className="panel editor-panel"><div className="panel-head"><div><div className="eyebrow">STRATEGY CODE</div><h2>策略編輯器 <Badge tone="blue">PINE SUBSET</Badge></h2></div><div className="toolbar"><button className="quiet-button" onClick={()=>{updateStrategy({type:'pine',code:samplePine});setSelectedStrategy('')}}><RefreshCw size={14}/> 載入範例</button><button className="quiet-button" onClick={()=>fileInput.current?.click()}><FileUp size={14}/> 匯入 .pine</button><button className="quiet-button" onClick={saveStrategy} disabled={!isPrivate||strategiesBusy}><Save size={14}/> 儲存策略</button><button className="icon-button" onClick={()=>setExpandEditor(x=>!x)} aria-label="收合策略編輯器">{expandEditor?<ChevronDown size={16}/>:<ChevronRight size={16}/>}</button></div></div>
            <input hidden ref={fileInput} type="file" accept=".pine,.txt" onChange={async e=>{const f=e.target.files?.[0];if(f){if(f.size>12000)setError('Pine 檔案超過 12 KB，現有策略子集無法載入');else{updateStrategy({type:'pine',code:await f.text()});setNotice('Pine 檔案已載入編輯器')}e.target.value=''}}}/>
            {expandEditor&&<><div className="editor-header"><input aria-label="策略名稱" value={strategyName} onChange={e=>setStrategyName(e.target.value)} placeholder="策略名稱"/><span>pine · v5/v6 相容子集</span></div>
               <div className="code-editor"><div className="line-numbers" aria-hidden="true">{Array.from({length:Math.max(12,(config.strategy.code||'').split('\n').length)},(_,i)=><div key={i}>{i+1}</div>)}</div><textarea spellCheck={false} aria-label="Pine Script 程式碼" value={config.strategy.code||''} onChange={e=>updateStrategy({type:'pine',code:e.target.value})} rows={14}/></div><div className="editor-foot"><span><ShieldCheck size={13}/> 安全 Pine 子集，尚非完整 TradingView Pine v6</span><span>{(config.strategy.code||'').length.toLocaleString()} 字元</span></div></>}
          </div>
          <div className="metrics-grid">{METRICS.slice(0,6).map(m=><MetricCard key={m.key} metric={m} value={result?.metrics?.[m.key]}/>)}</div>
          <div className="two-panels"><EquityChart points={result?.equity||result?.equity_preview||[]}/><div className="panel"><div className="panel-head"><div><div className="eyebrow">RECENT FILLS</div><h2>最新成交</h2></div><button className="quiet-button" onClick={()=>setView('analytics')}>全部交易 <ArrowRight size={14}/></button></div>
             {result?.fills?.length?<div className="mini-fills">{result.fills.slice(-6).reverse().map((f,i)=><div key={i}><span className={f.qty>0?'positive':'negative'}>{f.qty>0?'BUY':'SELL'}</span><strong>{fmt(f.price,3)}</strong><small>{dateAt(f.ts)}</small></div>)}</div>:empty('沒有成交資料','執行回測後這裡顯示最近交易。',<ArrowLeftRight size={24}/>)}</div></div>
        </div><aside className="workspace-settings"><section className="panel settings-panel"><div className="panel-head"><div><div className="eyebrow">BACKTEST CONFIGURATION</div><h2>回測設定</h2></div><Settings2 size={18} className="muted"/></div>
            <div className="settings-body"><SelectField label="行情來源" value={config.data.provider} onChange={v=>{setMarketMatches([]);setMarketQuery('');
 const symbol=v==='hyperliquid'?'BTC':v==='yfinance'?'AAPL':v==='demo'?'SYNTHETIC':'BTC/USDT:USDT';
 updateData({provider:v,exchange:v==='ccxt'?'binanceusdm':'',symbol,include_funding:false});
 if(v==='yfinance')updateRisk({product_type:'equity',market:'stock',leverage:1});
 else updateRisk({product_type:'perp',market:'crypto'});
 }}>{(sources?.providers||['ccxt','hyperliquid','yfinance']).filter(p=>isDemo||p!=='demo').map(p=><option key={p} value={p}>{({demo:'合成示範',ccxt:'CEX · CCXT',hyperliquid:'DEX · Hyperliquid',yfinance:'股票 · Yahoo Finance',csv:'本機 CSV'} as Record<string,string>)[p]||p}</option>)}</SelectField>
            {config.data.provider==='ccxt'&&<label className="field"><span>交易所 ID</span><input list="available-exchanges" value={config.data.exchange} onChange={e=>updateData({exchange:e.target.value})}/><datalist id="available-exchanges">{sources?.ccxt_exchanges_installed?.map(x=><option key={x} value={x}/>)}</datalist></label>}
            <label className="field"><span>交易商品</span><input value={config.data.symbol} onChange={e=>updateData({symbol:e.target.value})}/></label>
            {config.data.provider==='csv'&&<label className="field"><span>後端 CSV 路徑（私人主機）</span><input value={config.data.csv_path||''} onChange={e=>updateData({csv_path:e.target.value})}/></label>}
            {isPrivate&&['ccxt','hyperliquid','yfinance'].includes(config.data.provider)&&<div className="market-lookup"><label className="field"><span>市場搜尋</span><div className="input-row"><input value={marketQuery} onChange={e=>setMarketQuery(e.target.value)} onKeyDown={e=>e.key==='Enter'&&lookupMarkets()}/><button type="button" className="outline-button" disabled={marketBusy} onClick={lookupMarkets}>{marketBusy?<Loading/>:<Search size={16}/>}</button></div></label>{marketMatches.length>0&&<select size={Math.min(5,marketMatches.length)} className="market-results" aria-label="搜尋到的商品" onChange={e=>updateData({symbol:e.target.value})}>{marketMatches.map(x=><option key={x.symbol} value={x.symbol}>{x.symbol} {x.name||x.base||''}</option>)}</select>}</div>}
            <div className="field-row"><label className="field"><span>開始日期 (UTC)</span><input type="date" value={config.data.start.slice(0,10)} onChange={e=>updateData({start:e.target.value})}/></label><label className="field"><span>結束日期 (UTC)</span><input type="date" value={config.data.end.slice(0,10)} onChange={e=>{setFollowLive(false);updateData({end:e.target.value})}}/></label></div>
            <div className="field-row"><SelectField label="K 線週期" value={config.data.timeframe} onChange={v=>updateData({timeframe:v})}>{['1m','3m','5m','15m','30m','1h','2h','4h','8h','12h','1d','3d','1w'].map(x=><option key={x}>{x}</option>)}</SelectField><SelectField label="市場類型" value={config.data.market_type} onChange={v=>updateData({market_type:v})}><option value="spot">現貨</option><option value="swap">永續合約</option><option value="future">期貨</option></SelectField></div>
            <SelectField label="策略選擇" value={config.strategy.type==='pine'?'pine':config.strategy.name||'sma_cross'} onChange={v=>setConfig(c=>({...c,strategy:v==='pine'?{type:'pine',code:c.strategy.code||samplePine}:{type:'builtin',name:v,options:{fast:10,slow:30}}}))}><option value="pine">自訂 Pine Script</option><option value="sma_cross">SMA 均線交叉</option><option value="rsi_revert">RSI 回歸</option><option value="breakout">突破策略</option><option value="buy_hold">Buy & Hold</option></SelectField>
            <div className="field-row"><NumField label="起始資金 (USDT)" value={config.risk.initial_cash} onChange={v=>updateRisk({initial_cash:Number(v)})} min={1}/><NumField label="槓桿倍數" value={config.risk.leverage} onChange={v=>updateRisk({leverage:Number(v)})} min={1}/></div>
            <div className="field-row"><NumField label="手續費 (bps)" value={config.risk.fee_bps} onChange={v=>updateRisk({fee_bps:Number(v)})} min={0}/><NumField label="滑價 (bps)" value={config.risk.slippage_bps} onChange={v=>updateRisk({slippage_bps:Number(v)})} min={0}/></div>
            <div className="field-row"><SelectField label="部位類型" value={config.risk.product_type} onChange={v=>updateRisk({product_type:v,market:v==='equity'?'stock':'crypto',leverage:v==='equity'||v==='spot'?1:config.risk.leverage})}><option value="perp">永續合約</option><option value="future">期貨</option><option value="spot">現貨</option><option value="equity">股票</option></SelectField><NumField label="1R 停損參考 %" value={config.risk.r_reference_stop_pct} onChange={v=>updateRisk({r_reference_stop_pct:v===''?null:Number(v)})} min={.001}/></div>
            <label className="check-row"><input type="checkbox" checked={config.data.include_funding} disabled={isDemo} onChange={e=>updateData({include_funding:e.target.checked})}/><span>包含歷史資金費率</span></label>
            <label className="check-row"><input type="checkbox" checked={config.streaming} disabled={isDemo} onChange={e=>setConfig(c=>({...c,streaming:e.target.checked}))}/><span>SQLite 串流回測（節省 RAM）</span></label>
            <label className="check-row"><input type="checkbox" checked={config.refresh} disabled={isDemo} onChange={e=>setConfig(c=>({...c,refresh:e.target.checked}))}/><span>重新抓取行情</span></label>
            <button className="primary-button wide" onClick={runBacktest} disabled={busy}>{busy?<Loading/>:<Play size={17}/>} {busy?'回測運算中…':'啟動策略回測'} <ArrowRight size={16}/></button>
            <p className="form-disclaimer">1R 僅為統計用參考停損距離，並不會新增實際停損委託。使用者需自行驗證交易模型。</p>
            </div></section></aside></div>
      </>}
      {view==='strategies'&&<>
       <PageTitle kicker="STRATEGY LIBRARY / 02" title="策略工廠" sub="集中管理 Pine Script、內建策略、參數與歷史版本。" actions={<><button className="outline-button" onClick={()=>{setSelectedStrategy('');setStrategyName('新策略');updateStrategy({type:'pine',code:samplePine});setView('terminal')}}><Plus size={16}/> 新建策略</button></>}/>
       {!isPrivate?<Message>示範版支援直接在「交易研究台」編輯 Pine；持久化策略庫、版本與排程需要私人 API。</Message>:<div className="library-layout"><section className="panel"><div className="panel-head"><div><div className="eyebrow">SAVED STRATEGIES</div><h2>已儲存策略 <Badge tone="muted">{strategies.length}</Badge></h2></div><button className="icon-button" title="重新整理" onClick={()=>refreshLibrary()}><RefreshCw size={16}/></button></div>
        {strategies.length?<div className="strategy-list">{strategies.map(s=><div className="strategy-row" key={s.id}><div className="strategy-logo"><FileCode2 size={19}/></div><div className="strategy-detail"><strong>{s.name}</strong><span>{s.kind==='pine'?'Pine Script':s.strategy_name||'內建策略'} · v{s.revision||1} · {s.updated_at?.slice(0,16)}</span></div><Badge tone={s.kind==='pine'?'blue':'muted'}>{s.kind.toUpperCase()}</Badge><div className="row-actions"><button title="查看版本紀錄" className="icon-button" onClick={()=>showRevisions(s.id)}><History size={16}/></button><button title="載入" className="icon-button" onClick={()=>loadSaved(s)}><ArrowRight size={16}/></button><button title="刪除" className="icon-button danger" onClick={()=>removeStrategy(s.id)}><Trash2 size={16}/></button></div></div>)}</div>:empty('尚未儲存策略','回到工作台編輯 Pine，點選「儲存策略」建立第一個版本。',<FileCode2 size={24}/>)}
       </section><section className="panel info-panel">{revisionFor&&<div className="revision-block"><div className="panel-head"><h2>策略版本紀錄</h2><button className="icon-button" onClick={()=>setRevisionFor('')}><X size={16}/></button></div>{strategyRevisions.length?strategyRevisions.map(item=><div className="revision-row" key={String(item.revision)}><div><strong>v{String(item.revision)}</strong><small>{String(item.created_at||'')}</small></div><button className="outline-button slim" onClick={()=>restoreStrategy(revisionFor,Number(item.revision))}>還原</button></div>):<div className="small-empty">尚無版本紀錄</div>}</div>}<div className="eyebrow">STRATEGY WORKFLOW</div><h2>從程式碼到可重現研究</h2><div className="steps">{[['01','編寫與檢查','Pine 相容子集解析並拒絕不支援語法'],['02','儲存與版本','修改策略產生版本快照，便於回溯'],['03','完整歷史回測','依交易所原始資料計算，而非圖表縮減數據'],['04','驗證結果','確認費率、成交假設及樣本外風險']].map(([n,t,sub])=><div className="step" key={n}><span>{n}</span><div><strong>{t}</strong><p>{sub}</p></div></div>)}</div><button className="primary-button wide" onClick={()=>setView('terminal')}><Code2 size={16}/> 前往策略編輯器</button>
        <div className="ai-section"><div className="eyebrow">AI STRATEGY ASSISTANT</div><h2>自然語言產生策略草稿</h2><p>描述進出場條件，由私人伺服器呼叫選用的 AI 模型並檢查 Pine 相容性；不會直接執行或部署。</p>
        <label className="field"><span>策略描述</span><textarea rows={4} value={aiPrompt} onChange={e=>setAiPrompt(e.target.value)} placeholder="例如：使用 EMA 9/21 交叉進場，反向交叉平倉；避免未來函數"/></label>
        <button className="outline-button wide" disabled={aiBusy||!isPrivate} onClick={generateAI}>{aiBusy?<Loading/>:<Zap size={16}/>} 產生並檢查 Pine 草稿</button>
        <small>需在後端設定 UBT_AI_API_KEY；生成內容不保證獲利，必須先回測。</small></div></section></div>}
      </>}
      {view==='batch'&&<>
       <PageTitle kicker="MULTI-VENUE RESEARCH / 03" title="多市場回測中心" sub="同一策略並行評估不同交易所；或以共同資金研究跨市場價差策略。" actions={<button className="outline-button" onClick={()=>setView('terminal')}><ArrowRight size={16}/> 返回策略編輯器</button>}/>
       {!isPrivate&&<Message>此功能需要私人部署與授權。公開示範只提供單一合成行情回測。</Message>}
       <div className="batch-layout"><section className="panel batch-config"><div className="panel-head"><div><div className="eyebrow">VENUE MATRIX</div><h2>交易所矩陣</h2></div><Badge tone="blue">CEX + DEX</Badge></div><div className="panel-body"><label className="field"><span>市場清單（每行一個）</span><textarea className="market-textarea" spellCheck={false} value={batchText} onChange={e=>setBatchText(e.target.value)} rows={7}/><small>格式：provider,exchange,symbol[,fee_bps,slippage_bps]，同策略使用上方工作台參數。</small></label>
       <div className="field-row"><NumField label="要求的 Worker 數" value={batchWorkers} onChange={v=>setBatchWorkers(Number(v))} min={1}/><div className="field stat-preview"><span>選取的市場</span><strong>{batchText.split(/\r?\n/).filter(x=>x.trim()).length} 個</strong></div></div><button disabled={busy||!isPrivate} className="primary-button wide" onClick={()=>runBatch(false)}>{busy?<Loading/>:<Layers3 size={16}/>} 獨立市場批次回測</button>
       <div className="divider-space"/><h3>共同資金價差研究</h3><p className="muted small">所有交易所同步處理相同時間格點；各腿共享模擬資金。不是完整交易所保證金或真實鏈上套利模擬。</p>
       <div className="field-row"><NumField label="進場價差 (bps)" value={entryBps} onChange={v=>setEntryBps(Number(v))}/><NumField label="出場價差 (bps)" value={exitBps} onChange={v=>setExitBps(Number(v))}/></div><NumField label="共同資金名義曝險比例" value={gross} onChange={v=>setGross(Number(v))} step="0.05"/><button className="outline-button wide" disabled={busy||!isPrivate} onClick={()=>runBatch(true)}><ArrowLeftRight size={16}/> 共同資金跨市回測</button></div></section>
       <div className="batch-results"><section className="panel"><div className="panel-head"><div><div className="eyebrow">VENUE COMPARISON</div><h2>各交易所績效比較</h2></div><Badge tone="muted">{batchResults.length} MARKETS</Badge></div>
         {batchResults.length?<div className="table-scroll"><table><thead><tr><th>交易所／商品</th><th>狀態</th><th>淨利</th><th>勝率</th><th>PF</th><th>平均 R</th></tr></thead><tbody>{batchResults.map((row,i)=>{const d=row.data as Record<string,string>||{},rr=row.result as BacktestResult|undefined,m=rr?.metrics||{};return <tr key={i}><td><strong>{d.exchange||d.provider||'market'}</strong><br/><small>{d.symbol}</small></td><td><Badge tone={row.status==='success'?'good':'bad'}>{String(row.status||'unknown')}</Badge></td><td>{fmt(m.net_profit as number)}</td><td>{fmt(m.win_rate_pct as number)}%</td><td>{fmt(m.profit_factor as number)}</td><td>{fmt(m.average_r as number)} R</td></tr>})}</tbody></table></div>:empty('等待批次執行','回測結果將按交易所逐列比較，並保留個別失敗資訊。',<Layers3 size={24}/>)}
       </section><section className="panel"><div className="panel-head"><div><div className="eyebrow">SHARED ACCOUNT RESEARCH</div><h2>共同資金回測結果</h2></div></div>{portfolioResult?<div className="metrics-grid three">{METRICS.slice(0,6).map(m=><MetricCard key={m.key} metric={m} value={(portfolioResult.metrics as Record<string,unknown>)?.[m.key]}/>)}</div>:empty('尚無組合回測','至少選取兩個市場，使用共同帳戶執行價差策略。',<Wallet size={24}/>)}</section></div></div>
      </>}
      {view==='analytics'&&<><PageTitle kicker="PERFORMANCE INTELLIGENCE / 04" title="績效與風險分析" sub="統一使用已實現淨損益與完整收盤權益，避免不同頁面指標定義不一致。" actions={result&&<button className="outline-button" onClick={()=>downloadJSON(result,`backtest-${result.run_id||'demo'}.json`)}><Download size={15}/> 匯出回測 JSON</button>}/>
        {result?<><div className="metrics-grid wide-metrics">{METRICS.map(m=><MetricCard key={m.key} metric={m} value={result.metrics[m.key]}/>)}</div><div className="analysis-row"><EquityChart points={result.equity||result.equity_preview||[]}/><section className="panel"><div className="panel-head"><div><div className="eyebrow">RUN METADATA</div><h2>回測資訊</h2></div></div><dl className="detail-list"><div><dt>回測 ID</dt><dd>{result.run_id||'—'}</dd></div><div><dt>原始 K 線</dt><dd>{result.bars.toLocaleString()} 根</dd></div><div><dt>完整資料</dt><dd>{result.streaming_preview_only?'是（資金圖僅為縮減預覽）':'完整計算'}</dd></div><div><dt>已平倉交易</dt><dd>{fmt(result.closed_trades?.length,0)}</dd></div><div><dt>強制平倉</dt><dd>{config.risk.force_close?'是':'否'}</dd></div></dl></section></div>
        <section className="panel"><div className="panel-head"><div><div className="eyebrow">TRADE JOURNAL</div><h2>交易日誌</h2></div><div className="segmented">{(['trades','fills','warnings'] as const).map(tab=><button key={tab} className={indicatorTab===tab?'selected':''} onClick={()=>setIndicatorTab(tab)}>{tab==='trades'?'平倉交易':tab==='fills'?'成交明細':'模型假設'}</button>)}</div></div>
        {indicatorTab==='trades'?<div className="table-scroll"><table><thead><tr><th>平倉時間 UTC</th><th>方向</th><th>進場價</th><th>出場價</th><th>毛損益</th><th>淨損益</th><th>R 倍數</th><th>原因</th></tr></thead><tbody>{(result.closed_trades||[]).slice(-500).reverse().map((t,i)=><tr key={i}><td>{dateAt(t.ts)}</td><td>{(t.qty||0)>=0?'LONG':'SHORT'}</td><td>{fmt(t.entry_price,4)}</td><td>{fmt(t.exit_price,4)}</td><td>{fmt(t.gross_pnl)}</td><td className={t.net_pnl>=0?'positive':'negative'}>{signed(t.net_pnl)}</td><td>{fmt(t.r_multiple)} R</td><td>{t.reason}</td></tr>)}</tbody></table></div>:indicatorTab==='fills'?<div className="table-scroll"><table><thead><tr><th>成交時間 UTC</th><th>方向</th><th>成交價格</th><th>數量</th><th>手續費</th><th>原因</th></tr></thead><tbody>{(result.fills||[]).slice(-500).reverse().map((f,i)=><tr key={i}><td>{dateAt(f.ts)}</td><td className={f.qty>0?'positive':'negative'}>{f.qty>0?'BUY':'SELL'}</td><td>{fmt(f.price,4)}</td><td>{fmt(f.qty,5)}</td><td>{fmt(f.fee)}</td><td>{f.reason}</td></tr>)}</tbody></table></div>:<div className="assumptions">{[...(result.warnings||[]),...(result.assumptions||[])].map((x,i)=><div key={i}><InfoLine/> {x}</div>)}</div>}
        </section></>:empty('尚無回測績效','前往「交易研究台」執行策略後，即可查看勝率、最大回撤、PF、平均 R 與交易明細。',<BarChartBig size={24}/>)}
      </>}
      {view==='history'&&<><PageTitle kicker="RESEARCH ARCHIVE / 05" title="回測歷史紀錄" sub="重新載入已儲存的研究結果，跨策略比較交易假設。" actions={isPrivate&&<button className="outline-button" onClick={()=>refreshLibrary()}><RefreshCw size={15}/> 更新紀錄</button>}/>
       {!isPrivate?<Message>示範版不儲存回測紀錄。私人部署才會保存回測歷史。</Message>:<section className="panel"><div className="panel-head"><div><div className="eyebrow">BACKTEST RUNS</div><h2>最近回測 <Badge tone="muted">{runs.length}</Badge></h2></div></div>{runs.length?<div className="table-scroll"><table><thead><tr><th>執行時間</th><th>商品</th><th>策略</th><th>淨利</th><th>回測 ID</th><th>操作</th></tr></thead><tbody>{runs.map((x,i)=>{const cfg=x.config as Record<string,Record<string,unknown>>||{},metrics=x.metrics as Record<string,unknown>||{};const id=String(x.id||x.run_id||'');return <tr key={i}><td>{String(x.created_at||'—')}</td><td>{String(cfg.data?.symbol||x.symbol||'—')}</td><td>{String(cfg.strategy?.name||cfg.strategy?.type||'—')}</td><td>{fmt(metrics.net_profit as number)}</td><td className="mono">{id.slice(0,12)}</td><td><button className="quiet-button" onClick={()=>loadRun(id)}>檢視 <ArrowRight size={14}/></button></td></tr>})}</tbody></table></div>:empty('尚無回測紀錄','私人部署上的回測完成後，將出現在這裡。',<History size={24}/>)}</section>}
      </>}
      {view==='jobs'&&<><PageTitle kicker="OPERATIONS / 06" title="每日回測任務" sub="排程重跑已設定的策略，追蹤上次結果並控制啟用狀態。" actions={isPrivate&&<button className="primary-button" onClick={createJob} disabled={busy}><Plus size={16}/> 建立每日任務</button>}/>
       {!isPrivate?<Message>排程功能在公開示範中已停用。正式部署需另外啟動 Scheduler。</Message>:<section className="panel"><div className="panel-head"><div><div className="eyebrow">SCHEDULED RESEARCH</div><h2>回測排程</h2></div><button className="icon-button" onClick={()=>refreshJobs()}><RefreshCw size={16}/></button></div>{jobs.length?<div className="table-scroll"><table><thead><tr><th>任務 ID</th><th>商品</th><th>上次執行</th><th>執行結果</th><th>狀態</th><th>管理</th></tr></thead><tbody>{jobs.map((j,i)=>{const data=(j.config as Record<string,Record<string,unknown>>||{}).data||{};return <tr key={i}><td className="mono">{String(j.id).slice(0,12)}</td><td>{String(data.symbol||'—')}</td><td>{String(j.last_run_day||'尚未執行')}</td><td>{String(j.last_result||'—')}</td><td><Badge tone={j.active?'good':'muted'}>{j.active?'啟用':'停用'}</Badge></td><td><button className="outline-button slim" onClick={()=>toggleJob(String(j.id),!j.active)}>{j.active?'暫停':'啟用'}</button></td></tr>})}</tbody></table></div>:empty('沒有排程任務','先在研究台配置策略及市場，然後新增每日排程。',<Clock size={24}/>)}<div className="panel-footer">建立任務不代表背景排程器已啟動；必須另行運行 Scheduler 服務。</div></section>}
      </>}
      <footer className="app-footer"><span>UNIVERSAL BACKTESTER · Research / Simulation only</span><span>{health?.deployed_commit?`Build ${health.deployed_commit.slice(0,7)}`:'Deployment URL not verified'} · <a href="https://github.com/Davis1233798/universal-backtester" target="_blank" rel="noopener noreferrer">GitHub <ExternalLink size={12}/></a></span></footer>
     </>}
   </main></div></div>
}
function InfoLine(){return <AlertTriangle size={14} className="warn-icon"/>}
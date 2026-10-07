const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync('webapp/index.html','utf8');
const code=html.split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
const target={innerHTML:'',textContent:'',style:{display:'block'},value:'0',setAttribute(){},addEventListener(){},querySelectorAll(){return []}};
const ctx=vm.createContext({console,Date,Intl,Map,Number,JSON,document:{getElementById:()=>target}});vm.runInContext(code,ctx);
let checks=0;function check(v,msg){assert.ok(v,msg);checks++;}
const row={symbol:'THYAO',price:314.1,signal:'AL_ADAYI',signal_state:'YENI_AL',technical_score:82,confidence_score:78,confirmation_count:7,confirmation_total:9,confirmation_level:'GUCLU',signal_age_minutes:70,last_updated_at:'2026-10-08T10:10:00+03:00',data_quality:'GOOD',liquidity_status:'GOOD',buy_zone_low:312.4,buy_zone_high:314.1,take_profit:319.8,stop_loss:309.7,risk_reward_ratio:2.1,breakout_status:'CONFIRMED',VWAP:312,EMA9:313,EMA21:311,RSI:60,MACD:1,volume_ratio:158,OBV:1000,Bollinger:{lower:300,middle:310,upper:320},ATR:2,reasons:['VWAP: AL','<img src=x onerror=alert(1)>'],warnings:['<script>bad</script>']};
const frozen=JSON.stringify(row);const card=ctx.gunlukKart(row);
for(const s of ['THYAO','AL ADAYI','Teknik Güç','82/100','Güven','78/100','7/9 — Güçlü','Yeni AL','1 sa 10 dk','10:10','312,40','319,80','309,70','2,1','Hacimli kırılım gerçekleşti','EMA9','EMA21','VWAP','MACD','OBV','Bollinger','ATR','Neden AL?','Dikkat','&lt;img','&lt;script'])check(card.includes(s),s);
check(!card.includes('<img src=x'));check(JSON.stringify(row)===frozen);
for(const [k,v] of Object.entries({YENI_AL:'Yeni AL',AL_DEVAM:'AL Devam',ZAYIFLIYOR:'Zayıflıyor',SAT_DONUS:'SAT’a Döndü',YENI_SAT:'Yeni SAT',SAT_DEVAM:'SAT Devam',TOPARLANIYOR:'Toparlanıyor',IZLE:'İzle'}))check(ctx.gunlukKart({...row,signal_state:k}).includes(v),k);
for(const [k,v] of [['WEAK_CONFIRMATION','Fiyat kırdı, hacim teyidi zayıf'],['WAITING','Hacimli kırılım bekleniyor']])check(ctx.gunlukKart({...row,breakout_status:k}).includes(v));
for(const signal of ['SAT_ADAYI','IZLE']){const c=ctx.gunlukKart({...row,signal});check(!c.includes('Alım Bölgesi'));check(c.includes(signal==='SAT_ADAYI'?'Neden SAT?':'Teknik Durum'));}
const missing=ctx.gunlukKart({symbol:'X',signal:'AL_ADAYI',data_quality:'INSUFFICIENT',liquidity_status:'LOW',extended_move_penalty:5,stale:true,live_signal:false});
for(const s of ['Yeterli veri yok','—','Yetersiz veri','Likidite teyidi yetersiz','Aşırı uzama riski','Eski veri','canlı sinyal değil'])check(missing.includes(s));
check(ctx.gunlukYas(5)==='5 dk');check(ctx.gunlukYas(null)==='—');check(ctx.gunlukSaat('bad')==='—');
ctx.gunlukGoster();check(target.innerHTML.includes('yükleniyor'));
vm.runInContext('gunlukUI.report={enabled:false,signals:[]};gunlukGoster()',ctx);check(target.innerHTML.includes('devre dışı'));
vm.runInContext('gunlukUI.error=true;gunlukGoster()',ctx);check(target.innerHTML.includes('alınamıyor'));
vm.runInContext('gunlukUI.error=false;gunlukUI.report={enabled:true,market_open:false,signals:[]};gunlukGoster()',ctx);check(target.innerHTML.includes('Piyasa şu anda kapalı'));
vm.runInContext('gunlukUI.report.market_open=true;gunlukGoster()',ctx);check(target.innerHTML.includes('AL adayı bulunmuyor'));
check(html.includes('id="navDaily"'));check(html.includes('grid-template-columns:repeat(6'));check(html.includes('setInterval(gunlukYenile,60000)'));check(html.includes('document.hidden'));check(html.includes('viewport-fit=cover'));
(async()=>{
 const {chromium}=require('playwright');const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{for(const viewport of [{width:430,height:932},{width:1280,height:900}]){
 const page=await browser.newPage({viewport,isMobile:viewport.width===430,hasTouch:true});const errors=[];page.on('pageerror',e=>errors.push(e.message));let report={enabled:true,market_open:true,updated_at:row.last_updated_at,signals:[row,{...row,symbol:'ASELS',signal:'SAT_ADAYI',signal_state:'YENI_SAT'},{...row,symbol:'BIMAS',signal:'IZLE',signal_state:'IZLE'}]};let perfCount=10,apiError=false;const requests=[];
 await page.route('https://bist.test/**',route=>{const path=new URL(route.request().url()).pathname;requests.push(route.request().url());if(path==='/')return route.fulfill({contentType:'text/html',body:html});
 let data={};if(path==='/api/intraday-signals'){if(apiError)return route.fulfill({status:503,body:'{}'});data=report;}
 else if(path==='/api/intraday-signal-performance'){const horizon=new URL(route.request().url()).searchParams.get('horizon');data={groups:[{period:'all_time',horizon,signal:'AL',state:'YENI_AL',min_confidence:0,summary:{completed_count:perfCount,sample_count:perfCount,sample_size:perfCount,sufficient:perfCount>=30,success_rate:.6,mean_direction_return:1.2,reliability:'LOW',mean_MFE:2,mean_MAE:-1}}]};}
 else if(path.startsWith('/api/stocks/'))data={intraday_signal:row,otomatik:{},manuel:{},alarmlar:[]};
 else if(path.endsWith('bist_data.json'))data={hisseler:[],updated_at:row.last_updated_at};return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});});
 await page.goto('https://bist.test/');await page.locator('#navDaily').click();await page.waitForFunction(()=>document.querySelector('#dailyCards').textContent.includes('THYAO'));
 check((await page.locator('#dailyTabAL').textContent()).includes('(1)'));
 await page.locator('#dailyTabSAT').click();check((await page.locator('#dailyCards').textContent()).includes('ASELS'));
 await page.locator('#dailyTabIZLE').click();check((await page.locator('#dailyCards').textContent()).includes('BIMAS'));
 await page.locator('#dailyTabAL').click();await page.locator('#dailyConfidence').selectOption('90');check((await page.locator('#dailyCards').textContent()).includes('bulunmuyor'));await page.locator('#dailyConfidence').selectOption('0');
 check((await page.locator('#dailyPerformance').textContent()).includes('veri birikiyor'));perfCount=100;await page.evaluate(()=>gunlukPerformansYukle());check((await page.locator('#dailyPerformance').textContent()).includes('60,00%'));
 await Promise.all([page.waitForResponse(r=>r.url().includes('horizon=D3')),page.locator('#dailyHorizon').selectOption('D3')]);await page.waitForFunction(()=>document.querySelector('#dailyPerformance').textContent.includes('60,00%'));check(requests.some(r=>r.includes('horizon=D3')));
 const geom=await page.evaluate(()=>({w:innerWidth,scroll:document.documentElement.scrollWidth,overflow:getComputedStyle(document.getElementById('dailyPage')).overflowY}));check(geom.scroll<=geom.w,JSON.stringify(geom));check(geom.overflow==='auto');check(await page.locator('#dailyCards img').count()===0);
 await page.locator('[data-daily-stock="THYAO"]').click();await page.waitForFunction(()=>document.getElementById('stockDailySignal')?.textContent.includes('Günlük AL/SAT'));check(await page.locator('#stockPage').isVisible());await page.evaluate(()=>stockBack());await page.waitForFunction(()=>document.getElementById('dailyPage').style.display==='block');
 report={enabled:true,market_open:false,signals:[]};await page.evaluate(()=>gunlukYenile());check((await page.locator('#dailyCards').textContent()).includes('Piyasa şu anda kapalı'));
 report={enabled:false,signals:[]};await page.evaluate(()=>gunlukYenile());check((await page.locator('#dailyCards').textContent()).includes('devre dışı'));
 apiError=true;await page.evaluate(()=>gunlukYenile());check((await page.locator('#dailyCards').textContent()).includes('alınamıyor'));check(errors.length===0,errors.join(';'));await page.close();
 }}finally{await browser.close();}console.log('INTRADAY_SIGNAL_UI_OK: '+checks+' assertions, mobile/desktop mocked HTTP smoke');
})().catch(e=>{console.error(e);process.exitCode=1});

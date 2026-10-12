const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync('webapp/index.html','utf8');
const code=html.split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
const document={getElementById:()=>({style:{display:'block'}})};
const ctx=vm.createContext({console,Date,Intl,Map,Number,JSON,document});vm.runInContext(code,ctx);
const health={health_status:'IYI',main_model_success:.7,shadow_success:.8,live_sample_count:120,backtest_sample_count:60,shadow_sample_count:80,
 sources:{LIVE:{success_rate:.7}},most_common_error:'FALSE_AL',model_drift:{assessed:true,warning:'MODEL_DRIFT'},
 calibration:{confidence_warnings:[{}],confirmation_warnings:[]}};
const combo={confidence:'YETERLI',strong:true,shadow_contribution_proposal:.25,success_rate:.9};
const report={modes:{DAILY:health,INTRADAY:{...health,health_status:'YETERSIZ_VERI',model_drift:{assessed:false}}}};
const combinations={modes:{DAILY:{combinations:{1:{LIVE:{'VWAP+HACIM':combo,'MACD+RSI':{...combo,strong:false,shadow_contribution_proposal:-.25,success_rate:.2},'<script>':combo}}}}}};
const before=JSON.stringify([report,combinations]);const rendered=ctx.algoritmaSaglikGoster(report,combinations);
for(const text of ['Model Sağlığı','Gün İçi','Günlük','Learning: KAPALI','Ana Model','Shadow','Canlı başarı','LIVE','BACKTEST','SHADOW','En iyi kombinasyonlar','En kötü kombinasyonlar','FALSE_AL','Model Drift: Var','Yetersiz veri','Confidence / teyit'])assert.ok(rendered.includes(text),text);
assert.ok(rendered.includes('&lt;script&gt;'));assert.ok(!rendered.includes('<script>'));assert.equal(JSON.stringify([report,combinations]),before);
assert.ok(ctx.algoritmaSaglikGoster(null,null).includes('Yetersiz veri'));
assert.ok(ctx.algoritmaSaglikGoster({modes:{DAILY:{}}},{}).includes('Model Drift: Yetersiz veri'));
(async()=>{
 const urls=[];let output='';ctx.fetch=async url=>{urls.push(url);return {ok:true,json:async()=>url.includes('algoritma_saglik')?report:url.includes('kombinasyon_performansi')?combinations:{modes:{DAILY:{}}}}};
 await ctx.modelPerformansiYukle({insertAdjacentHTML:(p,value)=>output+=value});
 assert.ok(urls.some(url=>url.includes('algoritma_saglik.json')));assert.ok(urls.some(url=>url.includes('kombinasyon_performansi.json')));assert.ok(output.includes('Model Sağlığı'));
 ctx.fetch=async()=>{throw new Error('offline')};await ctx.modelPerformansiYukle({insertAdjacentHTML:(p,value)=>output+=value});
 document.getElementById=()=>({style:{display:'none'}});output='';await ctx.modelPerformansiYukle({insertAdjacentHTML:(p,value)=>output+=value});assert.equal(output,'');
 const {chromium}=require('playwright');
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:430,height:932},isMobile:true,hasTouch:true});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>Object.defineProperty(navigator,'standalone',{get:()=>true}));
  await page.route('https://bist.test/**',async route=>{
   const path=new URL(route.request().url()).pathname;
   if(path==='/')return route.fulfill({contentType:'text/html',body:html});
   const data=path.endsWith('algoritma_saglik.json')?report:path.endsWith('kombinasyon_performansi.json')?combinations:
       path.endsWith('kriter_performansi.json')?{modes:{DAILY:{}}}:path.endsWith('bist_data.json')?{hisseler:[],updated_at:new Date().toISOString()}:{};
   await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('https://bist.test/');await page.evaluate(()=>showAiLearning());
  await page.waitForFunction(()=>document.getElementById('aiLearningContent').textContent.includes('Model Sağlığı'));
  const panel=page.locator('#aiLearningContent');assert.ok(await panel.isVisible());
  for(const text of ['Canlı başarı','En iyi kombinasyonlar','En kötü kombinasyonlar','Learning: KAPALI','Model Drift: Var'])assert.ok((await panel.textContent()).includes(text),text);
  await page.locator('summary').filter({hasText:'En iyi kombinasyonlar'}).first().click();
  assert.ok((await panel.textContent()).includes('<script>'));
  assert.equal(errors.length,0,errors.join('; '));
  const geometry=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,overflow:getComputedStyle(document.getElementById('aiLearningPage')).overflowY}));
  assert.ok(geometry.scroll<=geometry.width,JSON.stringify(geometry));assert.equal(geometry.overflow,'auto');
 }finally{await browser.close()}
 console.log('ALGORITHM_HEALTH_UI_OK: isolated sources, compact health, combination evidence, escaping, offline and stale page guard');
})().catch(error=>{console.error(error);process.exitCode=1});

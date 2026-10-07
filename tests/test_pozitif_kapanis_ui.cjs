const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync('webapp/index.html','utf8');
const code=html.split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
const target={innerHTML:'',style:{display:'block'}};
const ctx=vm.createContext({console,Date,Intl,Map,Number,JSON,document:{getElementById:()=>target}});vm.runInContext(code,ctx);
const rows=Array.from({length:60},(_,i)=>({sembol:'ADAY'+(i+1),fiyat:100,degisim:.1,nihai_karar:{karar:'AL'},
 positive_opportunity:{rank:i+1,selection_rank:i+1,future_opportunity_score:90-i/2,expected_return_next_session:1.5,
 continuation_probability:70,confidence:60,risk:'ORTA',neden_bu_sirada:'Hacim <güçlü>',risks:['Örnek yetersiz'],probability_calibrated:false}}));
const snapshot={analiz_tarihi:'2026-10-06',top10:rows.slice(0,10),pozitif_havuz:{adaylar:rows,eligible_symbols:rows.map(r=>r.sembol),positive_count:280,analyzed_count:260}};
const before=JSON.stringify(snapshot);ctx.snapshot=snapshot;
vm.runInContext('pozitifYarinGorunumu={snapshot,live:new Map()};pozitifYarinGoster()',ctx);
for(const text of ['Günün En Güçlü Adayı','YARIN İÇİN TOP10','11–20','21–30','Gelecek fırsat','Devam olasılığı','DONDURULMUŞ TAHMİN','CANLI DURUM','Teknik senaryo'])assert.ok(target.innerHTML.includes(text),text);
assert.ok(target.innerHTML.includes('&lt;güçlü&gt;'));assert.ok(!target.innerHTML.includes('<güçlü>'));
assert.ok(!target.innerHTML.includes('31. ADAY31'));
ctx.pozitifListeSec(50);assert.ok(target.innerHTML.includes('50. ADAY50'));assert.ok(!target.innerHTML.includes('51. ADAY51'));
ctx.pozitifListeSec(20);assert.ok(target.innerHTML.includes('20. ADAY20'));assert.ok(!target.innerHTML.includes('21. ADAY21'));
ctx.pozitifListeSec(10);assert.ok(!target.innerHTML.includes('DİĞER GÜÇLÜ ADAYLAR'));
ctx.pozitifListeSec(999);assert.ok(!target.innerHTML.includes('DİĞER GÜÇLÜ ADAYLAR'));
assert.equal(JSON.stringify(snapshot),before);assert.equal(ctx.pozitifFirsatOzet({}),'');
assert.ok(ctx.pozitifOgrenmeGoster(null).includes('Learning: KAPALI'));
const report={analysis_date:'2026-10-06',positive_count:280,analyzed_count:260,missed_winner_count:2,horizons:{1:{stats:{success_rate:.7},capture:{top:{10:{continuation_success_rate:.8}}},patterns:{60:{combinations:{'<script>':{strong:true,success_rate:.9}}}}}}};
const learning=ctx.pozitifOgrenmeGoster(report);assert.ok(learning.includes('Pozitif Hisselerden Öğrenme'));assert.ok(learning.includes('80.00%'));assert.ok(learning.includes('&lt;script&gt;'));
for(const h of [1,2,3,5,10])assert.ok(learning.includes(h+'G · İşlem günü'));
assert.ok(learning.includes('MFE:'));assert.ok(learning.includes('MAE:'));assert.ok(learning.includes('Hangi vadede çalışıyor?'));
const ranked={...report,best_horizons:{combinations:{'<b>OBV</b>':{sufficient:true,best_horizon:3,conclusive:false}}}};
assert.ok(ctx.pozitifOgrenmeGoster(ranked).includes('&lt;b&gt;OBV&lt;/b&gt;: 3G'));assert.ok(ctx.pozitifOgrenmeGoster(ranked).includes('fark teyitli değil'));
(async()=>{
 const {chromium}=require('playwright');const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:430,height:932},isMobile:true,hasTouch:true});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>Object.defineProperty(navigator,'standalone',{get:()=>true}));
  await page.route('https://bist.test/**',async route=>{
   const path=new URL(route.request().url()).pathname;
   if(path==='/')return route.fulfill({contentType:'text/html',body:html});
   const data=path.includes('yarin_top10_arsiv')||path.endsWith('yarin_top10.json')?snapshot:path.endsWith('pozitif_hisseler_performansi.json')?report:
    path.endsWith('bist_data.json')?{hisseler:[],updated_at:new Date().toISOString()}:{};
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('https://bist.test/');await page.evaluate(()=>showTop10());
  await page.waitForFunction(()=>document.getElementById('top10List').textContent.includes('21–30'));
  await page.getByRole('button',{name:'TOP50',exact:true}).click();assert.ok((await page.locator('#top10List').textContent()).includes('50. ADAY50'));
  const geometry=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,overflow:getComputedStyle(document.getElementById('top10Page')).overflowY}));
  assert.ok(geometry.scroll<=geometry.width,JSON.stringify(geometry));assert.equal(geometry.overflow,'auto');
  await page.evaluate(()=>showAiLearning());await page.waitForFunction(()=>document.getElementById('aiLearningContent').textContent.includes('Pozitif Hisselerden Öğrenme'));
  assert.equal(errors.length,0,errors.join('; '));
 }finally{await browser.close()}
 console.log('POSITIVE_CLOSING_UI_OK: TOP10/20/30/50, frozen/live split, escaping, missing history, learning report, mobile HTTP smoke');
})().catch(e=>{console.error(e);process.exitCode=1});

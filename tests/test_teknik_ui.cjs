const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync('webapp/index.html','utf8');
const code=html.split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
const ctx=vm.createContext({console,Date,Intl,Map,Number,JSON,document:{getElementById:()=>({style:{display:'block'}})}});
vm.runInContext(code,ctx);
const doc={mode:'INTRADAY',data_time:new Date().toISOString(),confidence:100,stale:false,
  vwap:{status:'OK',session_value:100,position:'VWAP_USTU'},obv:{status:'OK',trend:'OBV_YUKSELEN'},
  bollinger:{status:'OK',squeeze_volume_momentum_break:true},momentum:{status:'OK',state:'GUCLENIYOR'}};
const original=JSON.stringify(doc);
let rendered=ctx.standartGostergelerGoster(doc);
for(const value of ['Seans VWAP','Üstünde','Güçlü','Hacimli kırılım','Güçleniyor','Gösterge zamanı','Güven'])assert.ok(rendered.includes(value),value);
assert.equal(JSON.stringify(doc),original);
assert.ok(ctx.standartGostergelerGoster(null).includes('--'));
assert.ok(ctx.standartGostergelerGoster({...doc,stale:true}).includes('Eski teknik veri'));
assert.ok(ctx.standartGostergelerGoster({...doc,mode:'TOMORROW',vwap:{status:'UNKNOWN',reference_20:100}}).includes('VWAP20 referansı'));
for(const [trend,text] of [['OBV_DUSEN','Zayıf'],['OBV_YATAY','Nötr']])assert.ok(ctx.standartGostergelerGoster({...doc,obv:{status:'OK',trend}}).includes(text));
for(const [state,text] of [['ZAYIFLIYOR','Zayıflıyor'],['NOTR','Nötr']])assert.ok(ctx.standartGostergelerGoster({...doc,momentum:{status:'OK',state}}).includes(text));
const entry={varken:{sample_count:40,success_rate:.75,median_return:2,trimmed_mean:1.5},confidence:'YETERLI'};
rendered=ctx.teknikKriterRaporuGoster({unit:'DAKIKA',vadeler:{5:{VWAP_USTU:entry},SEANS:{OBV_KIRILIM:entry}}},'Gün İçi');
for(const value of ['5 dk','Seans sonu','40','75','Medyan','Trim','Yeterli'])assert.ok(rendered.includes(value),value);
assert.ok(ctx.teknikKriterRaporuGoster({unit:'ISLEM_GUNU',vadeler:{1:{MOMENTUM_GUCLENME:entry}}},'Yarın').includes('1 işlem günü'));
assert.ok(!ctx.teknikKriterRaporuGoster({vadeler:{'<script>':{'<img src=x>':entry}}},'<script>').includes('<script>'));
assert.ok(ctx.teknikKriterRaporuGoster(null,'Gün İçi').includes('henüz'));
assert.ok(html.includes('standartGostergelerGoster(a.teknik_gostergeler)'));
(async()=>{
  const requests=[];let appended='';ctx.fetch=async url=>{requests.push(url);return{ok:true,json:async()=>({standart_teknik_kriterler:{unit:url.includes('gun_ici')?'DAKIKA':'ISLEM_GUNU',vadeler:{5:{VWAP_USTU:entry}}}})}};
  await ctx.teknikOlcumleriYukle({insertAdjacentHTML:(where,value)=>{appended+=value}});
  assert.equal(requests.length,2);assert.ok(appended.includes('Gün İçi'));assert.ok(appended.includes('Yarın'));assert.ok(appended.includes('otomatik ağırlık uygulaması kapalı'));
  console.log('TECHNICAL_UI_SMOKE_OK: normalized fields, legacy, stale, escaping, independent horizons, public report fetching');
})().catch(error=>{console.error(error);process.exitCode=1});

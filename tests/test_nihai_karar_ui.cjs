const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync('webapp/index.html','utf8');
const code=html.split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
const ctx=vm.createContext({console,Date,Intl,Map,Number,JSON,document:{getElementById:()=>({})}});vm.runInContext(code,ctx);
const final={karar:'AL',karar_puani:78,confidence:62,teknik_gucluluk:85,risk_puani:15,teyit_sayisi:4,teyit_toplam:6,
  ana_secim_nedeni:'VWAP üstü + hacim + momentum',ana_risk:'Piyasa rejimi negatif',pozitif_gerekceler:['Trend teyidi olumlu'],negatif_gerekceler:['Makro katkısı negatif'],
  zaman_dilimi:'INTRADAY',updated_at:new Date().toISOString(),veri_zamani:new Date().toISOString()};
const original=JSON.stringify(final);let rendered=ctx.nihaiKararGoster(final);
for(const item of ['Nihai Karar','AL',ctx.yarinSayi(78,'/100'),ctx.yarinSayi(62,'/100'),ctx.yarinSayi(85,'/100'),'4/6','Ana Neden','Ana Risk','VWAP','Gün İçi','Kararın gerekçeleri'])assert.ok(rendered.includes(item),item);
assert.equal(JSON.stringify(final),original);
for(const decision of ['GUCLU_AL','AL','BEKLE','SAT','GUCLU_SAT'])assert.ok(ctx.nihaiKararGoster({...final,karar:decision}).includes(decision));
rendered=ctx.nihaiKararGoster({...final,ana_risk:'<img src=x>',pozitif_gerekceler:['<script>evil</script>']});assert.ok(!rendered.includes('<script>evil'));assert.ok(!rendered.includes('<img src=x>'));
assert.ok(ctx.nihaiKararGoster(null).includes('güncel analiz bekleniyor'));
assert.ok(ctx.nihaiKararGoster({karar:'BEKLE'}).includes('--'));
assert.ok(html.includes('nihaiKararGoster(data.nihai_karar || context.otomatik.nihai_karar || data.ai_ozet?.nihai_karar)'));
assert.ok(ctx.otomatikSeviyeGoster({}).includes('Teknik karar'));assert.ok(ctx.otomatikSeviyeGoster({}).includes('Analiz AI puanı'));
console.log('FINAL_DECISION_UI_OK: five decisions, separate score/confidence, confirmation, reasons, escaping, legacy/missing fields');

const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync('webapp/index.html','utf8');const code=html.split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
const ctx=vm.createContext({console,Date,Intl,Map,Number,JSON,document:{getElementById:()=>({style:{display:'block'}})}});vm.runInContext(code,ctx);
const entry=delta=>({confidence:'YETERLI',success_difference:delta});const model={updated_at:new Date().toISOString(),shadow_active:true,minimum_samples:40,minimum_days:5,
 criteria:{1:{RSI:entry(.2),MACD:entry(-.2)}},comparisons:{OLD:{main:{success_rate:.5,sample_count:80},shadow:{success_rate:.8,sample_count:80},promotion_candidate:true}}};
const report={modes:{DAILY:model,INTRADAY:{...model,criteria:{60:{RSI:entry(.1)}}}}};const before=JSON.stringify(report);
const rendered=ctx.modelPerformansiGoster(report);
for(const word of ['Model Performansı','Gün İçi','Yarın / Günlük','Learning: KAPALI','Shadow: AKTİF','Ana model başarı','Shadow başarı','En güçlü 5','En zayıf 5','otomatik uygulama yok','40','5'])assert.ok(rendered.includes(word),word);
assert.equal(JSON.stringify(report),before);assert.ok(ctx.modelPerformansiGoster(null).includes('henüz'));
assert.ok(ctx.modelPerformansiGoster({modes:{DAILY:{shadow_active:false}}}).includes('PASİF'));
assert.ok(ctx.modelPerformansiGoster({modes:{DAILY:{criteria:{1:{'<script>':entry(.2)}}}}}).includes('&lt;script&gt;'));
(async()=>{let added='';ctx.fetch=async()=>({ok:true,json:async()=>report});await ctx.modelPerformansiYukle({insertAdjacentHTML:(position,value)=>{added=value}});assert.ok(added.includes('Model Performansı'));console.log('MODEL_PERFORMANCE_UI_OK: modes, independent validation, top criteria, disabled learning, low-data and escaping');})().catch(error=>{console.error(error);process.exitCode=1});

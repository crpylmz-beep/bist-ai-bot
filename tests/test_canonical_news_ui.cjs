const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync('webapp/index.html','utf8');
const code=html.split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
const nodes=new Map();
const ctx=vm.createContext({console,Date,Intl,Number,Map,Set,JSON,clearInterval:()=>{},document:{
 getElementById:id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',style:{},classList:{remove:()=>{},add:()=>{}}});return nodes.get(id)},querySelectorAll:()=>[]},
 fetch:async url=>({ok:true,json:async()=>url.includes('canonical_haberler')?{alarmlar:[{canonical_id:'one',id:'one',sembol:'XYZ',baslik:'<script>evil</script>',kaynak_etiketi:'KAP + ŞİRKET_SITE',tarih:'2026-10-06T12:00:00+03:00',etki_puani:2}]}:{alarmlar:[{id:'one',sembol:'XYZ',baslik:'legacy'}]}})});
vm.runInContext(code,ctx);
const canonical=[{canonical_id:'one',id:'one',sembol:'XYZ',baslik:'Yeni Haber',tarih:'2026-10-06T12:00:00+03:00'}];
const duplicate={id:'legacy',sembol:'XYZ',baslik:'Yeni Haber',tarih:'2026-10-06 12:00:00'};
assert.equal(ctx.haberListesiniBirlestir(canonical,[duplicate]).length,1);
assert.equal(ctx.haberListesiniBirlestir(canonical,[{...duplicate,sembol:'AAA'}]).length,2);
assert.equal(ctx.haberListesiniBirlestir(canonical,[{...duplicate,tarih:'2026-10-26 12:00:00'}]).length,2);
assert.equal(ctx.haberListesiniBirlestir([], [{id:'old',baslik:'Legacy'}]).length,1);
const name=Object.keys(ctx).find(k=>typeof ctx[k]==='function' && String(ctx[k]).includes('data/canonical_haberler.json'));
(async()=>{assert.ok(name);await ctx[name]();const rendered=nodes.get('kapAlarmList').innerHTML;
assert.equal((rendered.match(/class="detail-card"/g)||[]).length,1);
assert.ok(rendered.includes('KAP + ŞİRKET_SITE'));assert.ok(!rendered.includes('<script>evil</script>'));assert.ok(rendered.includes('&lt;script&gt;'));
console.log('CANONICAL_NEWS_UI_OK: single card, source label, legacy compatibility, escaping');
})().catch(error=>{console.error(error);process.exit(1)});

const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync('webapp/index.html','utf8');
const code=html.split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,{innerText:'',textContent:'',style:{},className:''});return elements.get(id)};
const stocks=[{sembol:'THYAO',fiyat:300,sinyal:'AGRESIF_ALIS'},{sembol:'ASELS',sinyal:'ASIRI_SATIM'}];
const ctx=vm.createContext({console,Date,Intl,Map,Number,JSON,document:{getElementById:element},
window:{isSecureContext:true,Notification:{},PushManager:{},matchMedia:()=>({matches:true}),location:{search:''}},
navigator:{userAgent:'iPhone',standalone:true},Notification:{permission:'default'},URLSearchParams,
fetch:async url=>({ok:true,json:async()=>url.includes('/api/push/config')?{configured:true,public_key:'key'}:
url.includes('gun_ici_tum')?{hisseler:[{sembol:'THYAO',fiyat:1}]}:
{hisseler:stocks,bist100:{fiyat:12345,degisim:1.2},updated_at:'2026-10-05T17:00:00+03:00'}})});
vm.runInContext(code,ctx);
(async()=>{
 await ctx.gercekVeriyiYukle(false);
 assert.equal(element('bistPrice').innerText,'12345.00');
 assert.equal(element('countAlis').innerText,1);
 assert.equal(element('countSatim').innerText,1);
 assert.ok(element('updateTime').innerText.includes('SON KAYIT'));
 assert.equal(vm.runInContext('tumVeriler[0].fiyat',ctx),300); // old intraday cannot replace newer daily price
 await ctx.pushDurumHazirla();assert.ok(element('pushStatus').textContent.includes('Bildirimleri Aç'));
 assert.ok(!element('pushStatus').textContent.includes('Ana Ekrana ekleyip'));
 ctx.navigator.standalone=false;ctx.window.matchMedia=()=>({matches:false});
 await ctx.pushDurumHazirla();assert.ok(element('pushStatus').textContent.includes('Ana Ekrana ekleyip'));
 assert.equal((html.match(/id="pushEnable"/g)||[]).length,1);
 assert.ok(html.includes('id="pushControls"'));
 assert.ok(!html.includes('id="pushEnable" disabled'));
 vm.runInContext('anaBist100 = {}; tumVeriler = []; anaSinyalVeriler = [];',ctx);
 ctx.anaSayfayiDoldur();assert.ok(element('bistPrice').innerText.includes('henüz alınamadı'));
 console.log('BOOTSTRAP_UI_OK: root index, historical signals, stale label, PWA notification control, empty data reason');
})().catch(error=>{console.error(error);process.exitCode=1});

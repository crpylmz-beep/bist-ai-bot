const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'../webapp/index.html'),'utf8');
const start=html.indexOf('function mergeFreshStockPrice');
const end=html.indexOf('\nlet tumVeriler',start);
const ctx={Date,Number};vm.createContext(ctx);vm.runInContext(html.slice(start,end),ctx);
const merge=ctx.mergeFreshStockPrice;
const base={fiyat:7.45,degisim:2,fiyat_zamani:'2026-10-13T18:10:00+03:00'};
const old={fiyat:7.43,degisim:1,fiyat_zamani:'2026-10-13T17:55:00+03:00',gun_ici_puan:80};
assert.equal(merge(base,old).fiyat,7.45);
assert.equal(merge(base,old).degisim,2);
assert.equal(merge(base,old).gun_ici_puan,80);
assert.equal(merge(base,{fiyat:7.4}).fiyat,7.45);
assert.equal(merge({fiyat:7.45},old).fiyat,7.45);
assert.equal(merge(base,{fiyat:7.5,fiyat_zamani:'2026-10-14T10:05:00+03:00'}).fiyat,7.5);
assert.equal(base.fiyat,7.45);
assert.equal(merge({...base,fiyat_turu:'SESSION_CLOSE'}, {...old,fiyat_zamani:'2026-10-13T18:15:00+03:00'}).fiyat,7.45);
console.log('price freshness PASS');
const closing={fiyat:7.45,onceki_kapanis:7.5,onceki_kapanis_tarihi:'2026-10-12',onceki_kapanis_beklenen_tarih:'2026-10-12',fiyat_zamani:base.fiyat_zamani,fiyat_turu:'SESSION_CLOSE'};
const merged=merge(closing,{...old,degisim:1.92,acilisa_gore_degisim:1.92});
assert.equal(ctx.dailyStockChange(merged).toFixed(2),'-0.67');
assert.equal(ctx.dailyStockChange({fiyat:7.45,degisim:1.92,acilisa_gore_degisim:1.92}),null);
assert.equal(ctx.dailyStockChange(merge(closing,{fiyat:7.6,fiyat_zamani:'2026-10-14T10:05:00+03:00'})),null);
assert.equal(ctx.dailyStockChange({...closing,onceki_kapanis_tarihi:'2026-10-09'}),null);
ctx.Date=class extends Date {static now(){return Date.parse('2026-10-13T19:00:00+03:00');}};
vm.runInContext('let tumVeriler=[];',ctx);
vm.runInContext('tumVeriler=[{sembol:"GENKM",fiyat:7.45,onceki_kapanis:7.5,onceki_kapanis_tarihi:"2026-10-12",onceki_kapanis_beklenen_tarih:"2026-10-12",fiyat_zamani:"2026-10-13T18:10:00+03:00",fiyat_turu:"SESSION_CLOSE",sonraki_islem_tarihi:"2026-10-14"}];',ctx);
const quote=ctx.currentStockQuote({sembol:'GENKM',fiyat:9,degisim:1.92,fiyat_zamani:'2026-10-14T18:10:00+03:00'});
assert.equal(quote.fiyat,7.45);assert.equal(ctx.dailyStockChange(quote).toFixed(2),'-0.67');
ctx.Date=class extends Date {static now(){return Date.parse('2026-10-14T10:05:00+03:00');}};
assert.equal(ctx.currentStockQuote({sembol:'GENKM'}).fiyat,7.45);
assert.equal(ctx.currentStockQuote({sembol:'GENKM'})._quote_status,'STALE');

assert.equal(ctx.mergeCanonicalQuote(closing,old).fiyat,7.45);
assert.equal(ctx.mergeCanonicalQuote(old,closing).fiyat,7.45);
assert.equal(ctx.mergeCanonicalQuote(closing,{fiyat:9,fiyat_zamani:'2026-10-15T10:00:00+03:00'}).fiyat,7.45);
vm.runInContext('tumVeriler=[{sembol:"GENKM",fiyat:7.45,fiyat_turu:"INTRADAY",fiyat_zamani:"2026-10-13T17:00:00+03:00",canli_guncelleme:"2026-10-14T10:05:00+03:00"}];',ctx);
assert.equal(ctx.currentStockQuote({sembol:'GENKM'})._quote_status,'STALE');
// A temporary canonical-file failure must not let an old analysis erase its last verified quote.
const loadStart=html.indexOf('async function gercekVeriyiYukle');
const loadEnd=html.indexOf('/* ANA SAYFA */',loadStart);
ctx.console={log(){},warn(){},error(){}};
ctx.document={querySelectorAll(){return []},getElementById(){return {innerText:''}}};
ctx.anaSayfayiDoldur=()=>{};
vm.runInContext('let fiyatYuklemeAktif=false;let merkeziFiyatlar=new Map();',ctx);
vm.runInContext(html.slice(loadStart,loadEnd),ctx);
let unavailable=false;
ctx.fetch=async url=>{
 if(url.includes('gun_ici_tum'))return {ok:false};
 if(url.includes('borsa_fiyatlari')){
  if(unavailable)throw new Error('offline');
  return {ok:true,json:async()=>({hisseler:[{...closing,sembol:'GENKM'}]})};
 }
 return {ok:true,json:async()=>({hisseler:[{...old,sembol:'GENKM'}]})};
};
(async()=>{
 await ctx.gercekVeriyiYukle();assert.equal(ctx.currentStockQuote({sembol:'GENKM'}).fiyat,7.45);
 unavailable=true;await ctx.gercekVeriyiYukle();assert.equal(ctx.currentStockQuote({sembol:'GENKM'}).fiyat,7.45);
 assert.equal(ctx.dailyStockChange(ctx.currentStockQuote({sembol:'GENKM'})).toFixed(2),'-0.67');
 console.log('canonical refresh outage PASS');
})().catch(error=>{console.error(error);process.exitCode=1});

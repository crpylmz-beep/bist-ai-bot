// Run the actual dashboard code with a minimal DOM and controlled HTTP responses.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'webapp/index.html'), 'utf8');
const code = html.split('<script>')[1].split('</script>')[0];
const elements = new Map();
let responses = {};
const requested = [];
const ctx = vm.createContext({
  console, Date, Intl, Map, Number, JSON,
  setInterval: () => 1, clearInterval: () => {},
  document: {getElementById(id) {
    if (!elements.has(id)) elements.set(id, {style:{}, innerHTML:'', textContent:''});
    return elements.get(id);
  }},
  fetch: async url => {
    const key = url.split('?')[0]; requested.push(key);
    const response = responses[key] || {status:404};
    return {ok:(response.status || 200)===200, status:response.status || 200,
      json:async()=>JSON.parse(JSON.stringify(response.body))};
  }
});
vm.runInContext(code.replace(/gercekVeriyiYukle\(\);\s*$/, ''), ctx);
const timestamp = new Date(Date.now()-60000).toISOString();
const frozen = {sembol:'THYAO',tahmin:{fiyat:100,skor:80,karar:'AL',alim_alt:99,
  alim_ust:101,hedef:110,stop:90,tahmin_zamani:timestamp,
  haber_puani:2,makro_puani:-1,kriter_ozeti:{nedenler:['Hacim <teyit>']}}};
const snapshot = {analiz_tarihi:'2026-10-06',tahmin_zamani:timestamp,top10:[frozen]};
const live = {canli:{fiyat:105,degisim:1.2,teknik_skor:73,ai_skor:75,karar:'IZLE',
  updated_at:timestamp},performans:{en_yuksek_yuzde:10,en_dusuk_yuzde:-10,
  hedefe_ulasti:true,stop_oldu:false}};
const original = JSON.stringify(snapshot);
let result = ctx.yarinTop10Karti(frozen,snapshot,live,1);
for(const label of ['CANLI DURUM','DONDURULMUŞ TAHMİN','TAHMİNDEN BERİ PERFORMANS',
  '105.00 TL','100.00 TL','5.00%','10.00%','-10.00%','Evet','Hayır',
  'Hacim &lt;teyit&gt;','(İstanbul)']) assert.ok(result.includes(label), label);
assert.ok(result.indexOf('CANLI DURUM') < result.indexOf('DONDURULMUŞ TAHMİN'));
assert.equal(JSON.stringify(snapshot),original);
for(const legacy of [{sembol:'OLD'},{},{sembol:'ZERO',fiyat:0}]) {
  result=ctx.yarinTop10Karti(legacy,{},{});
  assert.ok(result.includes('--'));
  assert.ok(!result.includes('NaN') && !result.includes('undefined') && !result.includes('Infinity'));
}
result=ctx.yarinTop10Karti(frozen,snapshot,{canli:{fiyat:105,updated_at:new Date(Date.now()-30*60000).toISOString()}});
assert.ok(result.includes('ESKİ VERİ'));
result=ctx.yarinTop10Karti(frozen,snapshot,{canli:{fiyat:105,updated_at:timestamp,fiyat_tarihi:'2000-01-01'}});
assert.ok(result.includes('Fiyat verisi bugüne ait değil'));
async function main() {
  responses={
    'data/yarin_top10.json':{body:{...snapshot,top10:[{sembol:'WRONG',fiyat:999}]}},
    'data/yarin_top10_arsiv/2026-10-06.json':{body:snapshot},
    'data/yarin_top10_canli.json':{body:{analiz_tarihi:'2026-10-06',top10:[{sembol:'THYAO',...live}]}}
  };
  await ctx.showTop10();
  result=elements.get('top10List').innerHTML;
  assert.ok(result.includes('105.00 TL') && result.includes('100.00 TL'));
  assert.ok(!result.includes('WRONG'));
  assert.ok(!requested.some(url=>url.includes('gun_ici')));
  responses['data/yarin_top10_canli.json'].body.analiz_tarihi='2026-10-05';
  await ctx.showTop10();
  assert.ok(!elements.get('top10List').innerHTML.includes('105.00 TL'));
  responses['data/yarin_top10_arsiv/2026-10-06.json']={status:404};
  responses['data/yarin_top10.json']={body:{analiz_tarihi:'2026-10-06',top10:[{sembol:'LEGACY'}]}};
  responses['data/yarin_top10_canli.json']={status:404};
  await ctx.showTop10();
  assert.ok(elements.get('top10List').innerHTML.includes('LEGACY'));
  assert.ok(elements.get('top10List').innerHTML.includes('--'));
  assert.equal(JSON.stringify(snapshot),original);
  console.log('WEB_CARD_SMOKE_OK: separation, performance base, archive source, missing legacy, stale/date mismatch, escaping, snapshot unchanged');
}
main().catch(e=>{console.error(e);process.exitCode=1;});

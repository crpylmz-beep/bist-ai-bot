const fs=require('fs');
const path=require('path');
const vm=require('vm');
const assert=require('assert/strict');
const html=fs.readFileSync(path.join(__dirname,'../webapp/index.html'),'utf8');
const code=html.split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
const store={levels:{},alarms:[]};
const automatic={alim_alt:290.05,alim_ust:292.25,hedef:296.24,stop:287.76,
  sat_kar_al:296.24,destek:280,direnc:300,risk_getiri:1.5,karar:'AL',
  nihai_ai_puan:80,guven:75,model:'GUNLUK',analiz_kimligi:'fixed',updated_at:'2026-10-06T12:00:00+03:00'};
const original=JSON.stringify(automatic);
let writes=0,delay=false;
function browser(){
  const elements=new Map();
  const buttons=[{disabled:false},{disabled:false}];
  const ctx=vm.createContext({console,Date,Intl,Map,Number,JSON,
    clearInterval:()=>{},setInterval:()=>1,
    document:{getElementById(id){
      if(!elements.has(id)) elements.set(id,{innerHTML:'',textContent:'',style:{},value:'',
        querySelectorAll:()=>buttons});
      return elements.get(id);
    },querySelectorAll:()=>[]},
    fetch:async(url,options={})=>{
      assert.equal(options.credentials,'same-origin');
      const method=options.method || 'GET';
      const pathname=url.split('?')[0];
      let result;
      const match=pathname.match(/^\/api\/stocks\/([^/]+)(?:\/(levels|alarms))?$/);
      if(match){
        const stock=match[1];
        if(method==='GET')result={manuel:store.levels[stock]||null,otomatik:automatic,
          alarmlar:store.alarms.filter(a=>a.sembol===stock)};
        if(method==='PUT'){
          writes++;
          store.levels[stock]={...JSON.parse(options.body),updated_at:'2026-10-06T12:00:00+03:00'};
          result=store.levels[stock];
        }
        if(method==='POST'){
          writes++;
          const body=JSON.parse(options.body);
          if(delay) await new Promise(r=>setTimeout(r,5));
          let a=store.alarms.find(a=>a.sembol===stock && a.alarm_turu===body.alarm_turu && a.aktif);
          const created=!a;
          if(!a){a={id:'a'.repeat(32),sembol:stock,kaynak:body.kaynak,alarm_turu:body.alarm_turu,
            hedef_fiyat:296.24,operator:'>=',aktif:true,created_at:'2026-10-06T12:00:00+03:00',triggered_at:null};store.alarms.push(a);}
          result={alarm:a,created};
        }
      }else{
        const id=pathname.split('/').at(-1);
        if(method==='PATCH')store.alarms.find(a=>a.id===id).aktif=false;
        if(method==='DELETE')store.alarms=store.alarms.filter(a=>a.id!==id);
        result={ok:true};
      }
      return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(result))};
    }
  });
  vm.runInContext(code,ctx);
  return {ctx,elements,buttons};
}
const flush=()=>new Promise(setImmediate);
async function main(){
  let {ctx,elements,buttons}=browser();
  const stock={sembol:'THYAO',fiyat:290.5,karar_giris_alt:290.05,karar_giris_ust:292.25,
    karar_hedef:296.24,karar_stop:287.76};
  const before=JSON.stringify(stock);
  ctx.hisseDetay(stock);
  await flush();
  assert.ok(elements.get('stockDetail').innerHTML.includes('🤖 BIST Asistanı Otomatik'));
  assert.ok(elements.get('stockDetail').innerHTML.includes('👤 Benim Seviyelerim'));
  assert.ok(elements.get('automaticLevels').innerHTML.includes('296.24'));
  assert.ok(buttons.every(b=>!b.disabled));
  for(const [key,value] of Object.entries({manuel_al:289,manuel_sat:300,manuel_stop:284,manuel_hedef:305})){
    elements.get(key).value=String(value);
  }
  await ctx.manuelSeviyeKaydet();
  assert.equal(store.levels.THYAO.manuel_al,289);
  assert.equal(elements.get('manuel_hedef').value,305);
  assert.equal(JSON.stringify(stock),before);
  assert.equal(JSON.stringify(automatic),original);
  // New page execution, same server/session: persisted levels reappear.
  ({ctx,elements,buttons}=browser());
  ctx.hisseDetay(stock);await flush();
  assert.equal(elements.get('manuel_al').value,289);
  ctx.hisseDetay({sembol:'EREGL'});await flush();
  assert.equal(elements.get('manuel_al').value,'');
  elements.get('manuel_al').value='24.5';await ctx.manuelSeviyeKaydet();
  assert.equal(store.levels.EREGL.manuel_al,24.5);
  assert.equal(store.levels.THYAO.manuel_al,289);
  ctx.hisseDetay(stock);await flush();
  ctx.document.getElementById('priceAlarmType').value='AI_HEDEF';
  ctx.fiyatAlarmTuruDegisti();
  assert.equal(elements.get('alarmPriceLabel').style.display,'none');
  delay=true;
  const prior=writes;
  await Promise.all([ctx.fiyatAlarmOlustur(),ctx.fiyatAlarmOlustur()]);
  assert.equal(writes-prior,1);
  assert.equal(store.alarms.length,1);
  assert.ok(elements.get('priceAlarmList').innerHTML.includes('Aktif · AI'));
  await ctx.fiyatAlarmOlustur();
  assert.ok(elements.get('levelsStatus').textContent.includes('zaten mevcut'));
  await ctx.fiyatAlarmDegistir('a'.repeat(32),false);
  assert.ok(elements.get('priceAlarmList').innerHTML.includes('Pasif · AI'));
  store.alarms[0].status='TRIGGERED';
  store.alarms[0].triggered_at='2026-10-06T12:00:00+03:00';
  store.alarms[0].triggered_price=305;
  elements.get('manuel_hedef').value='999';
  await ctx.fiyatAlarmlariYenile();
  assert.ok(elements.get('priceAlarmList').innerHTML.includes('TETİKLENDİ · AI'));
  assert.ok(elements.get('priceAlarmList').innerHTML.includes('305.00 TL'));
  assert.equal(elements.get('manuel_hedef').value,'999');
  await ctx.fiyatAlarmDegistir('a'.repeat(32),true);
  assert.equal(store.alarms.length,0);
  const triggeredHTML=ctx.fiyatAlarmListesi([{id:'a'.repeat(32),kaynak:'MANUEL',aktif:false,
    status:'TRIGGERED',triggered_price:305,triggered_at:'2026-10-06T09:00:00Z'}]);
  assert.ok(triggeredHTML.includes('TETİKLENDİ · MANUEL'));
  assert.ok(triggeredHTML.includes('305.00 TL'));
  assert.match(triggeredHTML,/6\.10\.2026.*12:00:00/);
  assert.ok(triggeredHTML.includes('(İstanbul)'));
  assert.ok(!triggeredHTML.includes('Pasif Yap'));
  const old=writes;
  elements.get('manuel_al').value='-1';await ctx.manuelSeviyeKaydet();
  assert.equal(writes,old);
  assert.equal(JSON.stringify(automatic),original);
  console.log('LEVELS_UI_SMOKE_OK: dual display, save/reload, stock isolation, immutable automatic fields, alarm list/actions, double-click prevention, validation');
}
main().catch(e=>{console.error(e);process.exitCode=1;});

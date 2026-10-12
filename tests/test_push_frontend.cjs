const fs=require('fs'), vm=require('vm'), assert=require('assert/strict');
const html=fs.readFileSync('webapp/index.html','utf8');
const code=html.split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
let permissions=0, registrations=0, saved=0, disabled=0, unsubscribed=0;
const ecdh=require('crypto').createECDH('prime256v1');
const validKey=ecdh.generateKeys().toString('base64url');
let configKey=validKey;
const storage=new Map(), element={textContent:''};
const subscription={endpoint:'https://fcm.googleapis.com/x',toJSON:()=>({endpoint:'https://fcm.googleapis.com/x',keys:{}}),unsubscribe:async()=>{unsubscribed++}};
const registration={pushManager:{getSubscription:async()=>subscription}};
const ctx=vm.createContext({console,Date,Intl,Map,Number,JSON,Uint8Array,atob,crypto:{randomUUID:()=> 'browser'},
 window:{isSecureContext:true,PushManager:{},Notification:{}},
 navigator:{userAgent:'test',serviceWorker:{register:async(path)=>{assert.equal(path,'/service-worker.js');registrations++},ready:Promise.resolve(registration),getRegistration:async()=>registration}},
 Notification:{requestPermission:async()=>{permissions++;return 'granted'}},
 localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 document:{getElementById:()=>element}, fetch:async(url,opts)=>({ok:true,json:async()=>{
 if(url.endsWith('/config'))return {configured:true,public_key:configKey};
 if(opts.method==='POST'){saved++;return {id:'a'.repeat(64)}}
 if(opts.method==='DELETE'){disabled++;return {active:false}};
 }})});
vm.runInContext(code,ctx);assert.equal(permissions,0);
(async()=>{
 await ctx.pushAc();assert.equal(permissions,1);assert.equal(registrations,1);assert.equal(saved,1);
 await ctx.pushKapat();assert.equal(disabled,1);assert.equal(unsubscribed,1);
 registration.pushManager.getSubscription=async()=>null;
 let subscribed=0;
 registration.pushManager.subscribe=async options=>{assert.equal(options.userVisibleOnly,true);assert.equal(options.applicationServerKey.length,65);assert.equal(options.applicationServerKey[0],4);subscribed++;return subscription};
 await ctx.pushAc();assert.equal(subscribed,1);assert.equal(saved,2);

 ctx.navigator.userAgent='iPhone';ctx.window.matchMedia=()=>({matches:false});await ctx.pushAc();assert.equal(permissions,2);
 ctx.navigator.userAgent='test';
 for(const key of ['', '%%%', 'eA', Buffer.alloc(65).toString('base64url')]){
  const before=subscribed;configKey=key;await ctx.pushAc();
  assert.equal(subscribed,before);
  assert.equal(element.textContent,'Bildirim anahtarı geçersiz. Sistem yöneticisi ayarı kontrol etmeli.');
 }
 configKey=validKey;
 for(const key of [validKey,validKey+'=', ' VAPID_PUBLIC_KEY="'+validKey+'" ']){
  const bytes=ctx.pushKey(key);assert.equal(bytes.length,65);assert.equal(bytes[0],4);
 }
 const events={}, notifications=[],opened=[];
 const sw=vm.createContext({URL,self:{location:{origin:'https://bist.example'},addEventListener:(type,fn)=>events[type]=fn,
 registration:{showNotification:async(title,options)=>notifications.push({title,options})},
 clients:{matchAll:async()=>[],openWindow:async url=>opened.push(url)}}});
 vm.runInContext(fs.readFileSync('webapp/service-worker.js','utf8'),sw);
 let wait;
 events.push({data:{json:()=>({id:'event',title:'THYAO',body:'300',url:'/?stock=THYAO'})},waitUntil:p=>wait=p});await wait;
 assert.equal(notifications[0].options.tag,'event');
 events.notificationclick({notification:{close:()=>{},data:notifications[0].options.data},waitUntil:p=>wait=p});await wait;
 assert.equal(opened[0],'https://bist.example/?stock=THYAO');
 events.notificationclick({notification:{close:()=>{},data:{url:'https://evil.example'}},waitUntil:p=>wait=p});await wait;
 assert.equal(opened[1],'https://bist.example/');
 sw.self.clients.matchAll=async()=>[{url:'https://bist.example/',navigate:async u=>opened.push(u),focus:async()=>{}}];
 events.notificationclick({notification:{close:()=>{},data:{url:'/?stock=ASELS'}},waitUntil:p=>wait=p});await wait;
 assert.equal(opened[2],'https://bist.example/?stock=ASELS');
 assert.ok(html.includes("row.sembol === stock"));
 console.log('Push frontend/service worker tests passed');
})().catch(e=>{console.error(e);process.exit(1)});

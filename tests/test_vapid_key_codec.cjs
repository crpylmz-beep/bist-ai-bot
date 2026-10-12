const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),{execFileSync}=require('child_process'),{webcrypto}=require('crypto');
const code=fs.readFileSync('webapp/index.html','utf8').split('<script>')[1].split('</script>')[0].replace(/gercekVeriyiYukle\(\);\s*$/,'');
const ctx=vm.createContext({console,Date,Intl,Map,Number,JSON,Uint8Array,atob,crypto:webcrypto,document:{getElementById:()=>({})}});
vm.runInContext(code,ctx);
const key=execFileSync(process.env.PYTHON || 'python',['-c',"from vapid_uret import generate; print(generate('test@example.com')['VAPID_PUBLIC_KEY'])"],{encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}).trim();
(async()=>{
 const bytes=ctx.pushKey(key);assert.equal(bytes.length,65);assert.equal(bytes[0],4);
 const imported=await webcrypto.subtle.importKey('raw',bytes,{name:'ECDSA',namedCurve:'P-256'},false,['verify']);
 assert.equal(imported.algorithm.namedCurve,'P-256');
 for(const value of ['',null,'%%%', 'eA',Buffer.alloc(64).toString('base64url'),Buffer.alloc(65).toString('base64url')]){
  assert.throws(()=>ctx.pushKey(value),/Bildirim anahtarı geçersiz/);
 }
 assert.deepEqual(Array.from(ctx.pushKey(' VAPID_PUBLIC_KEY="'+key+'" ')),Array.from(bytes));
 console.log('VAPID_CODEC_OK: Python generator -> frontend Uint8Array -> WebCrypto P-256; invalid keys rejected');
})().catch(error=>{console.error(error);process.exitCode=1});

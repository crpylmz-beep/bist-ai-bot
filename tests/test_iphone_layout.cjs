// Optional browser smoke: node tests/test_iphone_layout.cjs (Playwright + Chromium).
// iPhone 15 Pro Max dimensions and safe-area simulation; not a physical iOS test.
const fs=require('fs'),assert=require('assert/strict');
const {chromium}=require('playwright');
const html=fs.readFileSync('webapp/index.html','utf8');
const manifest=JSON.parse(fs.readFileSync('webapp/manifest.webmanifest','utf8'));
assert.equal(manifest.display,'standalone');assert.equal(manifest.orientation,'portrait');
assert.equal(manifest.start_url,'/');assert.equal(manifest.scope,'/');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try{
  for(const standalone of [true,false]){
   const context=await browser.newContext({viewport:{width:430,height:932},deviceScaleFactor:3,isMobile:true,hasTouch:true,userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'});
   await context.addInitScript(value=>Object.defineProperty(navigator,'standalone',{get:()=>value}),standalone);
   const page=await context.newPage();
   const stocks=Array.from({length:80},(_,i)=>({sembol:'TEST'+i,fiyat:100,sinyal:'AGRESIF_ALIS',puan:75}));
   await page.route('https://bist.test/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    let data={};
    if(path==='/'){return route.fulfill({contentType:'text/html',body:html})}
    if(path==='/health')data={ana_motor:{healthy:true}};
    if(path==='/data/bist_data.json')data={hisseler:stocks,bist100:{fiyat:12345,degisim:1,updated_at:new Date().toISOString()},updated_at:new Date().toISOString()};
    if(path==='/data/gun_ici_tum.json')data={hisseler:[]};
    if(path==='/manifest.webmanifest')data=manifest;
    await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
   });
   await page.goto('https://bist.test/');
   await page.waitForFunction(()=>document.getElementById('cloudStatus').textContent==='Sistem Aktif' && document.getElementById('bistPrice').textContent==='12345.00');
   await page.addStyleTag({content:'body{padding-top:59px!important}.bottom-nav{height:106px!important;padding-bottom:34px!important}'});
   assert.equal(await page.getAttribute('html','data-display-mode'),standalone?'standalone':'browser');
   assert.ok((await page.getAttribute('meta[name="viewport"]','content')).includes('viewport-fit=cover'));
   assert.ok(await page.locator('#pushEnable').isVisible());
   assert.ok(!(await page.locator('#pushActionMessage').isVisible()));
   const geometry=await page.evaluate(()=>{
    const home=document.getElementById('homePage');
    return {width:innerWidth,htmlWidth:document.documentElement.scrollWidth,htmlHeight:document.documentElement.scrollHeight,height:innerHeight,homeHeight:home.clientHeight,homeScroll:home.scrollHeight,bodyOverflow:getComputedStyle(document.body).overflow};
   });
   assert.ok(geometry.htmlWidth<=geometry.width,JSON.stringify(geometry));
   assert.ok(geometry.htmlHeight<=geometry.height,JSON.stringify(geometry));
   assert.ok(geometry.homeScroll<=geometry.homeHeight+2,JSON.stringify(geometry));
   assert.equal(geometry.bodyOverflow,'hidden');
   if(standalone)await page.screenshot({path:'/tmp/bist-iphone-pwa-layout.png'});
   await page.evaluate(()=>signalPage('AGRESIF_ALIS','home'));
   const scroll=await page.evaluate(()=>{const panel=document.getElementById('signalPage');panel.scrollTop=100;return {top:panel.scrollTop,height:panel.clientHeight,content:panel.scrollHeight,overflow:getComputedStyle(panel).overflowY}});
   assert.equal(scroll.overflow,'auto');assert.ok(scroll.content>scroll.height);assert.ok(scroll.top>0);
   console.log(`IPHONE_LAYOUT_OK: 430x932 safe-area 59/34, ${standalone?'standalone':'Safari'}, home fits, lists scroll`);
   await context.close();
  }
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});

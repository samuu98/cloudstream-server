const $=id=>document.getElementById(id);
let token='',providers=[],current='',player;
const status=text=>{$('status').textContent=text;};
async function api(route,body){
  const response=await fetch('/api/'+route,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},...(body?{body:JSON.stringify(body)}:{})});
  const result=await response.json();
  $('raw').textContent=JSON.stringify(result,null,2);
  if(!response.ok)throw Error(result.detail||result.error||'Richiesta fallita');
  return result;
}
async function run(action){status('Caricamento…');try{await action();status('');}catch(error){status(error.message);}}
function button(label,action,container,small){const b=document.createElement('button');b.className='card';b.textContent=label;if(small){const s=document.createElement('small');s.textContent=small;b.append(s);}b.onclick=()=>run(action);container.append(b);return b;}
function items(entries,parent){const grid=document.createElement('div');grid.className='cards';parent.append(grid);for(const item of entries||[])button(item.name||'Senza titolo',()=>load(item.url),grid,item.type);}
function render(data){$('results').replaceChildren();$('detail').replaceChildren();if(Array.isArray(data))items(data,$('results'));else if(data?.items&&Array.isArray(data.items)&&data.items[0]?.list){for(const section of data.items){const block=document.createElement('section');block.className='section';const h=document.createElement('h2');h.textContent=section.name;block.append(h);items(section.list,block);$('results').append(block);}}else items(data?.items||[], $('results'));}
function choose(){current=$('provider').value;const p=providers.find(p=>(p.id||p.name)===current);$('section').replaceChildren();(p?.mainPage||[]).forEach((s,i)=>{const o=new Option(s.name||'Catalogo',i);$('section').add(o);});}
async function connect(){let s;for(let attempt=0;attempt<90;attempt++){s=await api('status');if(['ready','partial','error'].includes(s.bootstrap.state))break;status('Preparazione delle sorgenti…');await new Promise(resolve=>setTimeout(resolve,2000));}if(s.bootstrap.state==='error')throw Error(s.bootstrap.error||'Caricamento estensioni fallito');if(!['ready','partial'].includes(s.bootstrap.state))throw Error('Le sorgenti sono ancora in preparazione. Ricarica la pagina tra poco.');providers=await api('providers');$('provider').replaceChildren();for(const p of providers)$('provider').add(new Option(p.displayName||p.name,p.id||p.name));choose();$('toolbar').hidden=false;$('search').hidden=false;status(providers.length+' sorgenti caricate');}
$('session').onsubmit=e=>{e.preventDefault();token=$('token').value.trim();run(connect);};
$('provider').onchange=choose;
$('home').onclick=()=>run(async()=>render(await api('provider/home',{provider:current,page:1,section:Number($('section').value||0)})));
$('search').onsubmit=e=>{e.preventDefault();run(async()=>render(await api('provider/search',{provider:current,query:$('query').value,page:1})));};
$('refresh').onclick=()=>run(async()=>{await api('repository',{});await connect();});
async function load(url){const data=await api('provider/load',{provider:current,url});$('detail').replaceChildren();const h=document.createElement('h2');h.textContent=data.name||'Dettagli';$('detail').append(h);if(data.plot){const p=document.createElement('p');p.textContent=data.plot;$('detail').append(p);}if(data.dataUrl)button('Trova stream',()=>resolve(data.dataUrl),$('detail'));let episodes=data.episodes;if(episodes&&!Array.isArray(episodes))episodes=Object.values(episodes).flat();for(const e of episodes||[])button(e.name||'Episodio '+(e.episode||''),()=>resolve(e.data),$('detail'),e.season?'Stagione '+e.season:undefined);}
async function resolve(data){const result=await api('provider/resolve',{provider:current,data});const block=document.createElement('div');block.className='cards';$('detail').append(block);if(!result.streams?.length)throw Error('La sorgente non ha restituito stream');for(const stream of result.streams)button(stream.name||'Riproduci',()=>play(stream),block,stream.type);}
function keyHex(value){if(/^[0-9a-f]{32}$/i.test(value))return value;const binary=atob(value.replace(/-/g,'+').replace(/_/g,'/'));return Array.from(binary,c=>c.charCodeAt(0).toString(16).padStart(2,'0')).join('');}
async function play(stream){shaka.polyfill.installAll();if(!shaka.Player.isBrowserSupported())throw Error('Il browser non supporta questo player');if(player)await player.destroy();const video=document.querySelector('video');player=new shaka.Player();await player.attach(video);player.addEventListener('error',e=>status('Errore player: '+e.detail.code));if(stream.key&&stream.kid){const keys={};keys[keyHex(stream.kid)]=keyHex(stream.key);player.configure({drm:{clearKeys:keys}});}else if(stream.licenseUrl){throw Error('Stream con licenza DRM: richiede un’integrazione specifica della sorgente');}$('player').hidden=false;await player.load(stream.playbackUrl,undefined,stream.type==='DASH'?'application/dash+xml':stream.type==='M3U8'?'application/x-mpegurl':undefined);await video.play();$('player').scrollIntoView({behavior:'smooth'});}

async function initialise(){try{const response=await fetch('/config');if(!response.ok)throw Error('Configurazione non disponibile');const config=await response.json();if(config.authRequired){$('session').hidden=false;}else{await connect();}}catch(error){status(error.message);}}
initialise();

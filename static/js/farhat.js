function goto(page){
  document.querySelectorAll('.page').forEach(function(p){p.classList.remove('active')});
  document.querySelectorAll('.nav-btn').forEach(function(b){b.classList.remove('active')});
  var p=document.getElementById('page-'+page);
  if(p){p.classList.add('active');p.scrollTop=0;}
  var b=document.querySelector('.nav-btn[data-page="'+page+'"]');
  if(b)b.classList.add('active');
  if(page==='careers')loadVacancies();
}
window.goto=goto;

var vacanciesLoaded=false;
function loadVacancies(){
  if(vacanciesLoaded)return;
  fetch('/api/v1/careers/vacancies/').then(function(r){return r.json()}).then(function(groups){
    var total=0,html='';
    groups.forEach(function(g){
      if(!g.vacancies.length)return;
      total+=g.vacancies.length;
      html+='<div class="branch-group"><div class="bg-header"><span class="bg-name">'+esc(g.branch_name)+'</span><span class="bg-count">'+g.vacancies.length+' open</span></div>';
      g.vacancies.forEach(function(v){
        var ft={FULL_TIME:'Full Time',PART_TIME:'Part Time',CONTRACT:'Contract'};
        var dt=v.closes_at?new Date(v.closes_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}):'';
        html+='<div class="v-card"><div><div class="v-name">'+esc(v.title)+'</div><div class="v-meta"><span class="v-tag">'+(ft[v.employment_type]||v.employment_type)+'</span><span class="v-tag">Closes '+dt+'</span></div></div><button class="v-apply" onclick="window.open(chr(39)+'https://wa.me/233556244194?text=Apply for '+esc(v.title)+chr(39)+','+chr(39)+'_blank'+chr(39)+')">Apply Now</button></div>';
      });
      html+='</div>';
    });
    if(!total)html='<div class="no-vacancies">No open positions at the moment. Check back soon.</div>';
    document.getElementById('vacancies-list').innerHTML=html;
    var el=document.getElementById('c-count');
    if(el)el.textContent=total||'0';
    vacanciesLoaded=true;
  }).catch(function(){
    document.getElementById('vacancies-list').innerHTML='<div class="no-vacancies">Could not load vacancies. Please try again later.</div>';
  });
}
window.loadVacancies=loadVacancies;

function joinWaitlist(){
  var el=document.getElementById('w-email');
  if(!el||!el.value.trim()||!el.value.includes('@')){alert('Please enter a valid email address.');return;}
  var b=document.querySelector('.w-btn');
  b.textContent='You are on the list';b.style.background='#1a9960';b.disabled=true;
}
window.joinWaitlist=joinWaitlist;

function esc(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

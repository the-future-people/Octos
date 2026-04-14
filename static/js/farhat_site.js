
(function(){
function goto(page){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
  var p=document.getElementById('page-'+page);
  if(p){p.classList.add('active');p.scrollTop=0;}
  var b=document.querySelector('.nav-btn[data-page="'+page+'"]');
  if(b)b.classList.add('active');
  if(page==='careers')loadVacancies();
}
window.goto=goto;

var vacanciesLoaded=false;
async function loadVacancies(){
  if(vacanciesLoaded)return;
  try{
    var r=await fetch('/api/v1/careers/vacancies/');
    var groups=await r.json();
    var total=0,html='';
    groups.forEach(function(g){
      if(!g.vacancies.length)return;
      total+=g.vacancies.length;
      html+='<div class="branch-group"><div class="bg-header"><span class="bg-name">'+esc(g.branch_name)+'</span><span class="bg-count">'+g.vacancies.length+' open</span></div>';
      g.vacancies.forEach(function(v){
        html+='<div class="v-card"><div><div class="v-name">'+esc(v.title)+'</div><div class="v-meta"><span class="v-tag">'+fmtType(v.employment_type)+'</span><span class="v-tag">Closes '+fmtDate(v.closes_at)+'</span></div></div><button class="v-apply" onclick="window.open('https://wa.me/233556244194?text=I would like to apply for the '+esc(v.title)+' position','_blank')">Apply Now</button></div>';
      });
      html+='</div>';
    });
    if(!total)html='<div class="no-vacancies">No open positions at the moment. Check back soon.</div>';
    document.getElementById('vacancies-list').innerHTML=html;
    var el=document.getElementById('c-count');
    if(el)el.textContent=total||'0';
    vacanciesLoaded=true;
  }catch(e){
    document.getElementById('vacancies-list').innerHTML='<div class="no-vacancies">Could not load vacancies. Please try again later.</div>';
  }
}

window.joinWaitlist=function(){
  var e=document.getElementById('w-email');
  if(!e||!e.value.trim()||!e.value.includes('@')){alert('Please enter a valid email address.');return;}
  var b=document.querySelector('.w-btn');
  b.textContent="You're on the list";
  b.style.background='#1a9960';
  b.disabled=true;
};

function esc(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function fmtType(t){return{FULL_TIME:'Full Time',PART_TIME:'Part Time',CONTRACT:'Contract'}[t]||t}
function fmtDate(d){if(!d)return'';return new Date(d).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})}
})();

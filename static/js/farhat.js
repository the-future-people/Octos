function switchPage(page){
  document.querySelectorAll('.page').forEach(function(p){p.classList.remove('active')});
  document.querySelectorAll('.nav-btn').forEach(function(b){b.classList.remove('active')});
  var p=document.getElementById('page-'+page);
  if(p){p.classList.add('active');p.scrollTop=0;}
  var b=document.querySelector('.nav-btn[data-page="'+page+'"]');
  if(b)b.classList.add('active');
  if(page==='careers')loadVacancies();
}

var vacanciesLoaded=false;
function loadVacancies(){
  if(vacanciesLoaded)return;
  fetch('/api/v1/careers/vacancies/').then(function(r){return r.json()}).then(function(groups){
    var total=0,html='';
    groups.forEach(function(g){
      if(!g.vacancies.length)return;
      total+=g.vacancies.length;
      html+='<div class="branch-group"><div class="bg-header">';
      html+='<span class="bg-name">'+esc(g.branch_name)+'</span>';
      html+='<span class="bg-count">'+g.vacancies.length+' open</span></div>';
      g.vacancies.forEach(function(v){
        var ft={FULL_TIME:'Full Time',PART_TIME:'Part Time',CONTRACT:'Contract'};
        var dt=v.closes_at?new Date(v.closes_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}):'';
        html+='<div class="v-card">';
        html+='<div><div class="v-name">'+esc(v.title)+'</div>';
        html+='<div class="v-meta"><span class="v-tag">'+(ft[v.employment_type]||v.employment_type)+'</span>';
        html+='<span class="v-tag">Closes '+dt+'</span></div></div>';
        html+='<button class="v-apply" onclick="openModal('+v.id+')">Apply Now</button>';
        html+='</div>';
      });
      html+='</div>';
    });
    if(!total)html='<div class="no-vacancies">No open positions at the moment.</div>';
    var vl=document.getElementById('vacancies-list');
    if(vl)vl.innerHTML=html;
    var el=document.getElementById('c-count');
    if(el)el.textContent=total||'0';
    vacanciesLoaded=true;
  }).catch(function(){
    var vl=document.getElementById('vacancies-list');
    if(vl)vl.innerHTML='<div class="no-vacancies">Could not load vacancies.</div>';
  });
}

var _vacancies={};
function openModal(id){
  var v=_vacancies[id];
  var title=v?v.title:'This Position';
  var branch=v?v.branch:'';
  document.getElementById('am-title').textContent=title;
  document.getElementById('am-branch').textContent=branch;
  document.getElementById('am-form').innerHTML=buildForm(id);
  document.getElementById('apply-modal').style.display='flex';
}

function closeApplyModal(){
  document.getElementById('apply-modal').style.display='none';
}

function buildForm(vacancyId){
  return [
    '<div class="am-row">',
    '<div class="am-group"><label class="am-label">First Name <span class="am-req">*</span></label>',
    '<input id="af-first" class="am-input" type="text" placeholder="Kwame"/></div>',
    '<div class="am-group"><label class="am-label">Last Name <span class="am-req">*</span></label>',
    '<input id="af-last" class="am-input" type="text" placeholder="Mensah"/></div></div>',
    '<div class="am-row">',
    '<div class="am-group"><label class="am-label">Email <span class="am-req">*</span></label>',
    '<input id="af-email" class="am-input" type="email" placeholder="kwame@email.com"/></div>',
    '<div class="am-group"><label class="am-label">Phone <span class="am-req">*</span></label>',
    '<input id="af-phone" class="am-input" type="tel" placeholder="024 000 0000"/></div></div>',
    '<div class="am-row am-single"><div class="am-group"><label class="am-label">Address</label>',
    '<input id="af-address" class="am-input" type="text" placeholder="Accra, Ghana"/></div></div>',
    '<div class="am-row am-single"><div class="am-group">',
    '<label class="am-label">Preferred Channel <span class="am-req">*</span></label>',
    '<div class="am-channels">',
    '<button type="button" class="am-ch active" data-ch="WHATSAPP" onclick="pickCh(this)">WhatsApp</button>',
    '<button type="button" class="am-ch" data-ch="SMS" onclick="pickCh(this)">SMS</button>',
    '<button type="button" class="am-ch" data-ch="EMAIL" onclick="pickCh(this)">Email</button>',
    '</div></div></div>',
    '<input type="hidden" id="af-vid" value="'+vacancyId+'"/>',
    '<input type="hidden" id="af-ch" value="WHATSAPP"/>',
    '<div class="am-row am-single"><div class="am-group">',
    '<label class="am-label">CV / Resume <span class="am-req">*</span></label>',
    '<label class="am-file"><input type="file" id="af-cv" accept=".pdf,.doc,.docx" onchange="showFn(this)"/> Choose file</label>',
    '<div class="am-file-name" id="cv-name"></div></div></div>',
    '<div class="am-row am-single"><div class="am-group">',
    '<label class="am-label">Cover Letter (optional)</label>',
    '<label class="am-file"><input type="file" id="af-cover" accept=".pdf,.doc,.docx" onchange="showFn2(this)"/> Choose file</label>',
    '<div class="am-file-name" id="cover-name"></div></div></div>',
    '<hr class="am-divider"/>',
    '<button type="button" class="am-submit" id="am-btn" onclick="submitApp()">Submit Application</button>'
  ].join('');
}

function pickCh(btn){
  document.querySelectorAll('.am-ch').forEach(function(b){b.classList.remove('active')});
  btn.classList.add('active');
  var h=document.getElementById('af-ch');
  if(h)h.value=btn.getAttribute('data-ch');
}

function showFn(inp){
  var l=document.getElementById('cv-name');
  if(l&&inp.files[0])l.textContent=inp.files[0].name;
}

function showFn2(inp){
  var l=document.getElementById('cover-name');
  if(l&&inp.files[0])l.textContent=inp.files[0].name;
}

function submitApp(){
  var first=document.getElementById('af-first').value.trim();
  var last=document.getElementById('af-last').value.trim();
  var email=document.getElementById('af-email').value.trim();
  var phone=document.getElementById('af-phone').value.trim();
  var cv=document.getElementById('af-cv').files[0];
  var vid=document.getElementById('af-vid').value;
  var ch=document.getElementById('af-ch').value;
  if(!first||!last||!email||!phone||!cv){
    alert('Please fill in all required fields and attach your CV.');return;
  }
  var btn=document.getElementById('am-btn');
  btn.textContent='Submitting...';btn.disabled=true;
  var fd=new FormData();
  fd.append('first_name',first);fd.append('last_name',last);
  fd.append('email',email);fd.append('phone',phone);
  fd.append('address',document.getElementById('af-address').value.trim());
  fd.append('preferred_channel',ch);
  fd.append('cv',cv);
  var cover=document.getElementById('af-cover').files[0];
  if(cover)fd.append('cover_letter',cover);
  if(vid)fd.append('vacancy',vid);
  fetch('/api/v1/careers/apply/',{method:'POST',body:fd})
    .then(function(r){return r.json().then(function(d){return{ok:r.ok,data:d}})})
    .then(function(res){
      if(!res.ok){
        alert(Object.values(res.data).flat().join(' ')||'Something went wrong.');
        btn.textContent='Submit Application';btn.disabled=false;return;
      }
      document.getElementById('am-form').innerHTML='<div class="am-success"><div class="am-success-icon">&#x2705;</div><h3>Application Received!</h3><p>Thank you '+esc(first)+'. We will be in touch.</p></div>';
    })
    .catch(function(){
      alert('Network error. Please try again.');
      btn.textContent='Submit Application';btn.disabled=false;
    });
}

function joinWaitlist(){
  var el=document.getElementById('w-email');
  if(!el||!el.value.trim()||!el.value.includes('@')){alert('Please enter a valid email.');return;}
  var b=document.querySelector('.w-btn');
  if(b){b.textContent='You are on the list';b.style.background='#1a9960';b.disabled=true;}
}

function esc(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
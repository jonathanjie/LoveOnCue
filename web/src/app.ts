export {};
type Dict = Record<string, unknown>;
type Member = {id:string;name:string;roles:string[];team_ids:string[];active:boolean;telegram_linked:boolean|null};
type Task = {id:string;title:string;instructions:string;owner_id:string;team_id:string;location_id:string;due_at:string;planned_due:string;state:string;version:number;acknowledged_at:string|null;completed_at:string|null;blocked_by:string[];overdue:boolean;mine:boolean;can_edit:boolean};
type Item = {id:string;title:string;planned_start:string;current_start:string;duration_minutes:number;location_id:string;team_ids:string[];status:string;instructions:string;latest_end:string|null;actual_start:string|null;actual_end:string|null};
type Change = {item_id:string;title:string;old_start:string;new_start:string;delta_minutes:number;team_ids:string[]};
type Approval = {id:string;title:string;reason:string;status:string;base_timeline_version:number;changes:Change[];blockers:string[];created_at:string;expires_at:string;decision_note:string|null};
type Notice = {id:string;topic:string;message:string;state:string;created_at:string;acknowledged_at:string|null;attempts:number;last_error:string|null};
type Issue = {id:string;title:string;details:string;severity:string;kind:string;status:string;created_at:string};
type Knowledge = {id:string;title:string;source_name:string;revision:number;status:string;verified_at:string|null;text:string|null;audience_team_ids:string[]};
type Guest = {id:string;name:string;table:string|null;location_id:string|null;attendance:string;rsvp:string;version:number;dietary?:string|null};
type GuestDetails = {id:string;name:string;table_id:string|null;rsvp:string;relationship:string|null;dietary:string|null;private_phone:string|null;version:number};
type Vendor = {id:string;name:string;category:string;status:string;contact_name:string;contact_phone:string;team_id:string;expected_at:string};
type Location = {id:string;name:string;directions:string;x:number;y:number};
type Table = {id:string;label:string;location_id:string;capacity:number;x:number;y:number};
type Snapshot = {wedding:{id:string;name:string;timezone:string;event_date:string;venue:string;status:string;state_version:number;timeline_version:number};now:string;me:{id:string;name:string;roles:string[];team_ids:string[];grants:string[]};teams:{id:string;name:string}[];members:Member[];locations:Location[];tables:Table[];tasks:Task[];timeline:Item[];incidents:Issue[];approvals:Approval[];notifications:Notice[];knowledge:Knowledge[];vendors:Vendor[];counts:{guests:number;onsite:number;open_incidents:number;pending_approvals:number}};
type Config = {demo:boolean;demo_members:Member[];agent_mode:string;telegram_configured:boolean;notifications_live:boolean};
type ChatReply = {kind:string;message:string;data?:Dict[];draft?:{id:string;summary:string;expires_at:string};engine:string;degraded:boolean;as_of:string};
type Preview = {id:string;count:number;errors:string[];error_count:number;sample:{name:string;table_id:string;rsvp:string}[]};
type TelegramWebApp = {initData:string;ready:()=>void;expand:()=>void};
declare global { interface Window {Telegram?:{WebApp?:TelegramWebApp}} }

let snapshot:Snapshot;
let config:Config;
let csrf='';
let sessionEpoch=0;
let page='overview';
let healthy=true;
let lastRefresh=0;
let guestQuery='';
let guestDiet=false;
let guestRows:Guest[]=[];
let guestSequence=0;
let polling=false;
let activeActions=0;
let main:HTMLElement;
let header:HTMLElement;
let nav:HTMLElement;
let chatLog:HTMLElement;
const app=document.querySelector<HTMLDivElement>('#app')!;
const toast=document.querySelector<HTMLDivElement>('#toast')!;
const navigation=[['overview','Overview'],['timeline','Run of show'],['tasks','My tasks'],['guests','Guest desk'],['people','People & teams'],['incidents','Issues'],['approvals','Approvals'],['venue','Venue & vendors'],['knowledge','Knowledge'],['audit','Audit trail'],['setup','Setup & imports']];

function el<K extends keyof HTMLElementTagNameMap>(tag:K,cls='',text=''):HTMLElementTagNameMap[K]{const node=document.createElement(tag);node.className=cls;if(text)node.textContent=text;return node;}
function group(cls:string,...nodes:(Node|string)[]):HTMLDivElement{const n=el('div',cls);n.append(...nodes);return n;}
function text(value:string,cls=''):HTMLParagraphElement{return el('p',cls,value);}
function badge(label:string,tone=''):HTMLSpanElement{return el('span',`badge ${tone}`,label.replaceAll('_',' '));}
function has(grant:string):boolean{return snapshot.me.grants.includes('*')||snapshot.me.grants.includes(grant);}
function coordinator():boolean{return snapshot.me.roles.includes('coordinator');}
function time(value:string|null):string{return value?new Intl.DateTimeFormat('en-SG',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:snapshot.wedding.timezone}).format(new Date(value)):'—';}
function teamName(id:string):string{return snapshot.teams.find(t=>t.id===id)?.name||id;}
function memberName(id:string):string{return snapshot.members.find(m=>m.id===id)?.name||'Assigned helper';}
function locationName(id:string|null):string{return snapshot.locations.find(l=>l.id===id)?.name||'Unassigned location';}
function requestId():string{const bytes=crypto.getRandomValues(new Uint8Array(16));return Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');}
function announce(message:string,error=false):void{toast.textContent=message;toast.className=error?'show error':'show';setTimeout(()=>{toast.className='';},8000);}
function errorText(error:unknown):string{return error instanceof Error?error.message:'The operation failed. Refresh and check the current state.';}
function button(label:string,action:()=>void|Promise<void>,kind='secondary'):HTMLButtonElement{
 const b=el('button',`button ${kind}`,label);b.type='button';
 b.addEventListener('click',()=>{if(b.disabled)return;b.disabled=true;activeActions++;Promise.resolve().then(action).catch(e=>announce(errorText(e),true)).finally(()=>{b.disabled=false;activeActions--;});});return b;
}
async function api<T>(path:string,body?:unknown,method?:string):Promise<T>{
 const response=await fetch(path,{method:method||(body===undefined?'GET':'POST'),credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,'X-WeddingOps-Client':'1'},...(body===undefined?{}:{body:JSON.stringify(body)})});
 const data:unknown=await response.json();
 if(!response.ok){const obj=data as {error?:{message?:string;details?:unknown}};throw new Error(obj.error?.message||`Request failed (${response.status})`);}return data as T;
}
async function command(payload:Dict):Promise<void>{
 if(!healthy)throw new Error('Connection is stale. Refresh successfully before making changes.');
 const request={command:payload,request_id:requestId()};
 try{await api('/api/commands',request);}catch(e){if(e instanceof TypeError){await api('/api/commands',request);}else throw e;}
 announce('Recorded. The authoritative state has been refreshed.');await refresh(true);
}
function section(title:string,description?:string):HTMLElement{const s=el('section','section');s.append(el('h2','',title));if(description)s.append(text(description,'muted'));return s;}
function empty(message:string):HTMLElement{return group('empty',text(message));}
function field(label:string,value='',type='text'):{wrap:HTMLLabelElement;input:HTMLInputElement}{const wrap=el('label','field');wrap.append(el('span','field-label',label));const input=el('input');input.type=type;input.value=value;input.autocomplete='off';wrap.append(input);return {wrap,input};}
function area(label:string,value=''):{wrap:HTMLLabelElement;input:HTMLTextAreaElement}{const wrap=el('label','field');wrap.append(el('span','field-label',label));const input=el('textarea');input.value=value;input.rows=4;wrap.append(input);return {wrap,input};}
function selectField(label:string,options:{id:string;name:string}[],chosen?:string):{wrap:HTMLLabelElement;input:HTMLSelectElement}{const wrap=el('label','field');wrap.append(el('span','field-label',label));const input=el('select');for(const item of options){const o=el('option','',item.name);o.value=item.id;input.append(o);}if(chosen)input.value=chosen;wrap.append(input);return {wrap,input};}
function allowedPage(name:string):boolean{
 if(name==='tasks')return has('tasks:read');if(name==='guests')return has('guests:seating')||has('guests:dietary');
 if(name==='approvals')return coordinator()||has('timeline:propose');if(name==='audit'||name==='setup')return coordinator();return true;
}

async function signIn(memberId:string):Promise<void>{sessionEpoch++;const data=await api<{csrf:string}>('/api/auth/demo',{member_id:memberId});csrf=data.csrf;guestRows=[];guestQuery='';guestDiet=false;page='overview';await load();}
async function boot():Promise<void>{
 try{
  config=await api<Config>('/api/config');
  const params=new URLSearchParams(location.hash.slice(1));const invitation=params.get('invite');
  if(invitation){history.replaceState(null,'',location.pathname);const data=await api<{csrf:string}>('/api/auth/invite',{token:invitation});csrf=data.csrf;await load();return;}
  try{const session=await api<{csrf:string}>('/api/session');csrf=session.csrf;await load();return;}catch{/* No authenticated session yet. */}
  const telegram=window.Telegram?.WebApp;
  if(telegram?.initData){telegram.ready();const data=await api<{csrf:string}>('/api/auth/telegram',{init_data:telegram.initData});csrf=data.csrf;telegram.expand();await load();return;}
  renderLogin();
 }catch(e){app.replaceChildren(group('loading',el('h1','','WeddingOps'),text(errorText(e),'error-text'),button('Try again',boot)));}
}
function renderLogin():void{
 const card=group('login-card',el('div','wordmark','WeddingOps'),el('h1','','A clear next step.\nFor everyone.'),text('Role-aware coordination for the people making the day happen.','muted'));
 if(config.demo){card.append(badge('Fictional rehearsal','warning'),text('Choose a demo role. No real guests, Telegram messages or model credentials are used.','muted'));for(const m of config.demo_members)card.append(button(`${m.name} · ${m.roles.join(', ')}`,()=>signIn(m.id),'login-role'));}
 else{card.append(text('Open your personal invitation from the coordinator, or sign in through the enrolled Telegram bot. Roles cannot be selected here.'));}
 app.replaceChildren(group('login',card));
}
async function load():Promise<void>{const epoch=sessionEpoch;const next=await api<Snapshot>('/api/snapshot');if(epoch!==sessionEpoch)return;snapshot=next;lastRefresh=Date.now();healthy=true;buildLayout();render();}
function buildLayout():void{
 const sidebar=el('aside','sidebar');sidebar.append(el('div','wordmark','WeddingOps'),el('div','eyebrow','THE OPERATIONS DESK'));nav=el('nav','navigation');nav.setAttribute('aria-label','Main navigation');sidebar.append(nav);
 sidebar.append(group('sidebar-footer',text('Human-led. State-backed.'),text('The agent proposes.\nYour coordinator decides.','muted small')));
 const work=el('div','work');header=el('header','header');main=el('main','main');main.id='main-content';work.append(header,main);
 const skip=el('a','skip','Skip to content');skip.href='#main-content';app.replaceChildren(skip,sidebar,work);
 const assistantPanel=el('aside','assistant-panel');assistantPanel.setAttribute('aria-label','Operations assistant');assistantPanel.append(group('assistant-heading',el('h2','','Ask operations'),badge(config.agent_mode==='mistral'?'Model-assisted':'Deterministic')),
 text('Answers from current state. Reports need your confirmation.','muted small'));
 chatLog=el('div','chat-log');chatLog.setAttribute('aria-live','polite');assistantPanel.append(chatLog);
 const shortcuts=group('shortcuts',button('My next step',()=>ask('/now'),'chip'),button('Service lift',()=>ask('/knowledge service lift'),'chip'));
 if(has('timeline:propose'))shortcuts.append(button('Dinner +12 min',()=>ask('Dinner needs another 12 minutes'),'chip'));
 if(has('family:report'))shortcuts.append(button("Locate bride's father",()=>ask("Bride's father isn't here yet"),'chip'));
 if(has('guests:arrival'))shortcuts.append(button("Parents arrived",()=>ask("Bride's parents just arrived"),'chip'));
 assistantPanel.append(shortcuts);
 const form=el('form','chat-form');const input=el('textarea');input.rows=2;input.maxLength=2000;input.placeholder='Ask a question or report a change…';input.setAttribute('aria-label','Message for the operations assistant');
 const submit=el('button','button primary','Send');submit.type='submit';form.append(input,submit);form.addEventListener('submit',e=>{e.preventDefault();const value=input.value.trim();if(value){input.value='';submit.disabled=true;void ask(value).catch(err=>announce(errorText(err),true)).finally(()=>{submit.disabled=false;});}});
 assistantPanel.append(form,text('For urgent safety issues, contact the on-site team directly.','safety-note'));work.append(assistantPanel);
}
function renderNav():void{nav.replaceChildren();for(const [name,label] of navigation){if(!name||!label||!allowedPage(name))continue;const b=button(label,()=>{page=name;render();},`nav-button ${page===name?'active':''}`);if(page===name)b.setAttribute('aria-current','page');nav.append(b);}}
function renderHeader():void{
 header.replaceChildren();
 const identity=group('header-title',el('div','eyebrow',snapshot.wedding.venue),el('h1','',snapshot.wedding.name),group('metadata',badge(snapshot.wedding.status,'green'),text(`Run sheet v${snapshot.wedding.timeline_version} · ${snapshot.wedding.event_date}`,'small muted')));
 const status=group('header-status',el('div','live-time',time(snapshot.now)),text(snapshot.wedding.timezone,'small muted'),badge(healthy?'Connected':'Connection stale',healthy?'green':'danger'));
 const controls=group('header-controls',button('Refresh',()=>refresh(true),'small-button'));
 if(config.demo){const role=selectField('Rehearsal role',config.demo_members.map(m=>({id:m.id,name:`${m.name} · ${m.roles[0]}`})),snapshot.me.id);role.input.addEventListener('change',()=>{void signIn(role.input.value).catch(e=>announce(errorText(e),true));});controls.append(role.wrap);if(coordinator())controls.append(button('+5 min',async()=>{await api('/api/demo/tick',{minutes:5});await refresh(true);},'small-button'),button('Run reminders',async()=>{const r=await api<{processed:number}>('/api/demo/tick',{minutes:0});announce(`${r.processed} notifications processed in simulation. Nothing sent externally.`);await refresh(true);},'small-button'));}
 else controls.append(text(`${snapshot.me.name} · ${snapshot.me.roles.join(', ')}`,'small'),button('Sign out',async()=>{await api('/api/logout',{});sessionEpoch++;csrf='';renderLogin();},'small-button'));
 header.append(identity,status,controls);
 if(config.demo)header.append(group('demo-bar',text('REHEARSAL · 180 fictional guests · simulated event clock · no external messages','small')));
}
function render():void{
 if(!allowedPage(page))page='overview';renderNav();renderHeader();main.replaceChildren();
 if(!healthy)main.append(group('warning-box',text('Data may be out of date. Mutations are paused until a successful refresh. Use your exported run sheet and contact the coordinator.')));
 const screens:Record<string,()=>void>={overview:overview,timeline:timeline,tasks:tasks,guests:guests,people:people,incidents:incidents,approvals:approvals,venue:venue,knowledge:knowledge,audit:auditScreen,setup:setup};screens[page]?.();
}
async function refresh(force=false):Promise<void>{
 const epoch=sessionEpoch;const member=snapshot.me.id;
 try{const next=await api<Snapshot>('/api/snapshot');if(epoch!==sessionEpoch||snapshot.me.id!==member)return;const changed=next.wedding.state_version!==snapshot.wedding.state_version||next.wedding.timeline_version!==snapshot.wedding.timeline_version;snapshot=next;healthy=true;lastRefresh=Date.now();const focus=document.activeElement?.tagName;
 if(force||((changed||page==='overview')&&!['INPUT','TEXTAREA','SELECT','BUTTON'].includes(focus||'')&&activeActions===0))render();else renderHeader();
 }catch(e){if(epoch!==sessionEpoch)return;healthy=false;renderHeader();if(force)throw e;}
}
function taskCard(t:Task):HTMLElement{
 const card=group(`task-card ${t.overdue?'is-overdue':''}`,group('row between',el('h3','',t.title),badge(t.state,t.overdue?'warning':'')),text(t.instructions,'muted'),group('metadata',text(`${time(t.due_at)} · ${locationName(t.location_id)}`,'small'),text(`${memberName(t.owner_id)} · ${teamName(t.team_id)}`,'small muted')));
 if(t.blocked_by.length)card.append(text('Waiting on: '+t.blocked_by.join(', '),'blocked small'));
 if(t.acknowledged_at)card.append(text(`Acknowledged ${time(t.acknowledged_at)}`,'small muted'));
 if(t.can_edit&&!['done','cancelled'].includes(t.state)){
  const actions=group('actions');
  if(!t.acknowledged_at)actions.append(button('Acknowledge',()=>command({type:'task_action',task_id:t.id,action:'acknowledge',expected_version:t.version})));
  if(t.state==='pending'){const b=button('Start',()=>command({type:'task_action',task_id:t.id,action:'start',expected_version:t.version}));b.disabled=t.blocked_by.length>0;actions.append(b);}
  const complete=button('Mark complete',()=>command({type:'task_action',task_id:t.id,action:'complete',expected_version:t.version}),'primary');complete.disabled=t.blocked_by.length>0;actions.append(complete);card.append(actions);
 }return card;
}
function overview():void{
 const title=section(coordinator()?'Command centre':'Your operations brief',coordinator()?'A shared operational picture, with a human in command.':`Signed in as ${snapshot.me.name}. Only your role's operational details are shown.`);
 const metrics=group('metrics');for(const [value,label] of [[`${snapshot.counts.onsite}/${snapshot.counts.guests}`,'Guests onsite'],[snapshot.counts.open_incidents,'Open issues'],[snapshot.counts.pending_approvals,'Awaiting approval'],[snapshot.tasks.filter(t=>t.overdue).length,'Overdue in your view']])metrics.append(group('metric',el('strong','metric-value',String(value)),text(String(label),'small muted')));title.append(metrics);main.append(title);
 const open=snapshot.tasks.filter(t=>!['done','cancelled'].includes(t.state));const next=section(coordinator()?'Needs attention':'Now & next');
 if(open.length)for(const task of (coordinator()?[...open].sort((a,b)=>Number(b.overdue)-Number(a.overdue)):open.filter(t=>t.mine)).slice(0,4))next.append(taskCard(task));else next.append(empty('No open tasks in your role.'));
 main.append(next);const messages=section('Your updates','Sent, simulated and unacknowledged messages are shown explicitly.');
 if(!snapshot.notifications.length)messages.append(empty('No updates for you yet.'));
 for(const n of snapshot.notifications.slice(0,8)){const card=group('notice',group('row between',badge(n.topic),badge(n.state,n.state==='failed'?'danger':'')),text(n.message),text(`${time(n.created_at)} · ${n.attempts} delivery attempts`,'small muted'));if(n.last_error)card.append(text(n.last_error,'small error-text'));if(!n.acknowledged_at)card.append(button('I have read this',()=>command({type:'acknowledge_notification',notification_id:n.id}),'small-button'));else card.append(text(`Read ${time(n.acknowledged_at)}`,'small muted'));messages.append(card);}main.append(messages);
}
function timeline():void{
 const s=section('Run of show',`Version ${snapshot.wedding.timeline_version}. Planned times remain preserved; current and actual times are separate.`);
 for(const item of snapshot.timeline){const card=group('timeline-card',group('timeline-time',el('strong','',time(item.current_start)),text(`${item.duration_minutes} min`,'small muted')),group('timeline-body',group('row between',el('h3','',item.title),badge(item.status,item.status==='live'?'green':'')),text(`${locationName(item.location_id)} · ${item.team_ids.map(teamName).join(', ')}`,'small muted'),text(item.instructions)));
 const body=card.querySelector('.timeline-body')!;
 if(item.planned_start!==item.current_start)body.append(text(`Originally ${time(item.planned_start)}`,'small changed'));
 if(item.latest_end)body.append(text(`Hard latest end: ${time(item.latest_end)}`,'small warning-text'));
 if(item.actual_start)body.append(text(`Actual start ${time(item.actual_start)}${item.actual_end?' · finished '+time(item.actual_end):''}`,'small'));
 const actions=group('actions');
 if(item.status==='scheduled'&&has('timeline:propose')&&(coordinator()||item.team_ids.some(t=>snapshot.me.team_ids.includes(t))))actions.append(button('Report a delay',async()=>{const minutes=prompt(`Additional delay for ${item.title}, in minutes:`,'12');if(minutes===null)return;const value=Number(minutes);if(!Number.isInteger(value)||value<1||value>180)throw new Error('Use a whole number from 1 to 180.');await command({type:'propose_delay',item_id:item.id,minutes:value,reason:'Delay reported through the operations desk.'});page='approvals';render();},'small-button'));
 if(coordinator()&&item.status!=='complete')actions.append(button(item.status==='scheduled'?'Confirm started':'Confirm finished',async()=>{if(confirm(`Record that ${item.title} has ${item.status==='scheduled'?'started':'finished'} now?`))await command({type:'timeline_action',item_id:item.id,action:item.status==='scheduled'?'start':'complete',expected_timeline_version:snapshot.wedding.timeline_version});},'small-button'));
 body.append(actions);s.append(card);
 }main.append(s);
}
function tasks():void{const s=section('My tasks','Ownership, prerequisites and acknowledgement are explicit. You cannot complete another team’s tasks.');if(!snapshot.tasks.length)s.append(empty('No tasks assigned to you or your team.'));for(const t of snapshot.tasks)s.append(taskCard(t));main.append(s);}
function guests():void{
 const s=section('Guest desk','Search the approved guest list. Similar names remain separate records; confirm the correct person before marking arrival.');const search=field('Guest name',guestQuery);search.input.placeholder='Search Sarah Tan…';
 let timer:number;search.input.addEventListener('input',()=>{guestQuery=search.input.value;clearTimeout(timer);timer=window.setTimeout(()=>void searchGuests().catch(e=>announce(errorText(e),true)),250);});s.append(search.wrap);
 if(has('guests:dietary')){const check=field('Show dietary service notes','','checkbox');check.input.checked=guestDiet||!has('guests:seating');check.input.addEventListener('change',()=>{guestDiet=check.input.checked;void searchGuests().catch(e=>announce(errorText(e),true));});s.append(check.wrap);}
 const results=el('div');results.id='guest-results';s.append(results);main.append(s);renderGuests();if(!guestRows.length)void searchGuests().catch(e=>announce(errorText(e),true));
}
async function searchGuests():Promise<void>{const sequence=++guestSequence;const id=snapshot.me.id;const result=await api<{items:Guest[]}>(`/api/guests?q=${encodeURIComponent(guestQuery)}&sensitive=${guestDiet||!has('guests:seating')}`);if(sequence===guestSequence&&snapshot.me.id===id){guestRows=result.items;renderGuests();}}
function renderGuests():void{
 const results=document.querySelector('#guest-results');if(!results)return;results.replaceChildren();if(!guestRows.length)results.append(empty('No matching guests. Ask the coordinator to check the list.'));
 for(const g of guestRows){const card=group('guest-card',group('',el('h3','',g.name),text(`Table ${g.table||'unassigned'} · ${locationName(g.location_id)}`,'muted small')),badge(g.attendance,g.attendance==='onsite'?'green':''));if(g.dietary)card.append(text(g.dietary,'dietary small'));
 if(has('guests:arrival')&&g.attendance!=='onsite')card.append(button('Confirm arrival',async()=>{if(confirm(`Confirm ${g.name} is onsite?`)){await command({type:'arrival',person_ids:[g.id],status:'onsite'});await searchGuests();}},'small-button'));if(coordinator())card.append(button('Edit guest / family role',()=>editGuest(g.id,card),'small-button'));results.append(card);}
 results.append(text('Showing up to 50 matches. Narrow the name to find additional guests.','small muted'));
}
async function editGuest(id:string,card:HTMLElement):Promise<void>{
 const entry=await api<GuestDetails>(`/api/guests/${encodeURIComponent(id)}/details`);
 card.querySelector('.guest-editor')?.remove();
 const name=field('Guest name',entry.name);const table=selectField('Assigned table',[{id:'',name:'Unassigned'},...snapshot.tables.map(t=>({id:t.id,name:`Table ${t.label}`}))],entry.table_id||'');
 const rsvp=selectField('RSVP',['yes','no','unknown'].map(v=>({id:v,name:v})),entry.rsvp);
 const relation=field('Family role (blank removes family access)',entry.relationship||'');
 relation.input.placeholder='father_of_bride, mother_of_groom, or another descriptive role';
 const dietary=field('Dietary service notes',entry.dietary||'');const phone=field('Private contact phone',entry.private_phone||'');
 const editor=group('guest-editor form-card',text('Private contact phones are available only to the coordinator and designated family liaison.','small warning-text'),name.wrap,table.wrap,rsvp.wrap,relation.wrap,dietary.wrap,phone.wrap,
 button('Save reviewed guest details',async()=>{if(confirm('Save these guest details and family-contact visibility?')){await command({type:'edit_guest',person_id:id,expected_version:entry.version,name:name.input.value,table_id:table.input.value||null,rsvp:rsvp.input.value,relationship:relation.input.value||null,dietary:dietary.input.value||null,private_phone:phone.input.value||null});await searchGuests();}},'primary'));
 const role=selectField('Helper role',['helper','registration','usher','photographer','family_liaison','banquet','mc','av','transport','team_lead'].map(v=>({id:v,name:v.replaceAll('_',' ')})));const team=selectField('Helper team',snapshot.teams);
 editor.append(text('A guest can also be a helper without duplicating their guest record.','small muted'),role.wrap,team.wrap,button('Create membership for this guest',async()=>{if(confirm('Grant this guest the selected role and team?'))await command({type:'create_member',person_id:id,roles:[role.input.value],team_ids:[team.input.value]});},'small-button'));
 card.append(editor);
}
function people():void{
 const s=section('People & teams','Permissions are assigned by the coordinator, never inferred from a chat message.');
 if(has('family:contacts')){const box=el('div');s.append(button('Show authorized family contacts',async()=>{const response=await api<{items:{name:string;relationship:string;private_phone:string|null}[]}>('/api/family/contacts');box.replaceChildren();for(const person of response.items)box.append(group('person-card',text(`${person.name} · ${person.relationship.replaceAll('_',' ')}`),text(person.private_phone||'No contact number recorded','small')));if(!response.items.length)box.append(empty('No designated family contacts. A coordinator can assign family roles in Guest desk.'));},'small-button'),box);}

 for(const m of snapshot.members){const card=group('person-card',group('',el('h3','',m.name),text(m.team_ids.map(teamName).join(' · '),'small muted')),group('badges',...m.roles.map(r=>badge(r))),badge(m.active?'Active':'Revoked',m.active?'green':'danger'));
 if(coordinator()&&m.active){card.append(text(m.telegram_linked?'Telegram linked':'Not linked to Telegram','small muted'),button('Personal invitation',async()=>{const invite=await api<{web_url:string;telegram_url:string|null}>('/api/invitations',{member_id:m.id});const box=group('invite-box',text('Secret, one-use link. Share only with this person. Expires in 24 hours.','small warning-text'));const input=field('Invitation link',invite.telegram_url||invite.web_url);input.input.readOnly=true;box.append(input.wrap,button('Copy link',async()=>{await navigator.clipboard.writeText(input.input.value);announce('Invitation copied.');},'small-button'));card.append(box);},'small-button'));
 if(m.id!==snapshot.me.id)card.append(button('Revoke access',async()=>{if(confirm(`Revoke ${m.name}'s access immediately?`))await command({type:'revoke_member',member_id:m.id});},'small-button danger-button'));}s.append(card);
 }main.append(s);
}
function incidents():void{
 const s=section('Issues','An unconfirmed location is not the same as an absence. Reports route to relevant teams.');
 if(has('incidents:report')){const title=field('Issue title');const details=area('What happened? Who needs to know?');const box=group('form-card',title.wrap,details.wrap,button('Report issue',()=>command({type:'report_incident',kind:'logistics',title:title.input.value,details:details.input.value}),'primary'));s.append(box);}
 if(!snapshot.incidents.length)s.append(empty('No issues visible to your role.'));
 for(const i of [...snapshot.incidents].reverse()){const card=group('issue-card',group('row between',el('h3','',i.title),badge(i.status,i.status==='open'?'warning':'green')),text(i.details),text(`${i.kind.replaceAll('_',' ')} · ${time(i.created_at)}`,'small muted'));if(coordinator()&&i.status==='open')card.append(button('Resolve',async()=>{const note=prompt('How was this resolved?');if(note)await command({type:'resolve_incident',incident_id:i.id,note});},'small-button'));s.append(card);}main.append(s);
}
function approvals():void{
 const s=section('Approvals','Nothing below changes the master schedule until a coordinator reviews and approves the exact proposal.');
 if(!snapshot.approvals.length)s.append(empty('No proposals yet. The banquet demo role can report “Dinner needs another 12 minutes.”'));
 for(const p of [...snapshot.approvals].reverse()){const expired=new Date(p.expires_at)<=new Date(snapshot.now);const stale=p.base_timeline_version!==snapshot.wedding.timeline_version;const pending=p.status==='pending';const card=group('approval-card',group('row between',el('h3','',p.title),badge(pending&&expired?'expired':p.status,pending?'warning':'green')),text(p.reason,'muted'),text(`Based on run sheet v${p.base_timeline_version} · review by ${time(p.expires_at)}`,'small muted'));
 const grid=el('table','data-table');grid.append(tableHeader(['Activity','Current','Proposed','Shift']));const body=el('tbody');for(const c of p.changes){const tr=el('tr');for(const value of [c.title,time(c.old_start),time(c.new_start),`+${c.delta_minutes} min`])tr.append(el('td','',value));body.append(tr);}grid.append(body);card.append(grid);
 for(const b of p.blockers)card.append(text(b,'error-text'));if(pending&&stale)card.append(text('Stale proposal: the run sheet has changed. Generate a new proposal.','warning-text'));
 if(coordinator()&&pending){const approve=button('Approve reviewed change',async()=>{if(confirm('Approve these exact schedule changes and notify the affected teams?'))await command({type:'decide_approval',approval_id:p.id,decision:'approve'});},'primary');approve.disabled=expired||stale||p.blockers.length>0;card.append(group('actions',approve,button('Reject',()=>command({type:'decide_approval',approval_id:p.id,decision:'reject'}))));}
 s.append(card);
 }main.append(s);
}
function tableHeader(titles:string[]):HTMLTableSectionElement{const head=el('thead');const row=el('tr');for(const t of titles)row.append(el('th','',t));head.append(row);return head;}
function venue():void{
 const s=section('Venue & vendors','Schematic layout only. Follow venue signage and approved instructions onsite.');
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 100 100');svg.setAttribute('class','floorplan');svg.setAttribute('role','img');svg.setAttribute('aria-label','Schematic table positions and venue zones');
 for(const t of snapshot.tables){const circle=document.createElementNS(svg.namespaceURI,'circle');circle.setAttribute('cx',String(t.x));circle.setAttribute('cy',String(t.y));circle.setAttribute('r','3.6');circle.setAttribute('class','map-table');svg.append(circle);const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',String(t.x));label.setAttribute('y',String(t.y+1));label.setAttribute('class','map-label');label.textContent=t.label;svg.append(label);}
 for(const l of snapshot.locations){const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',String(l.x));label.setAttribute('y',String(l.y));label.setAttribute('class','zone-label');label.textContent=l.name;svg.append(label);}s.append(svg);
 for(const l of snapshot.locations)s.append(group('location-card',el('h3','',l.name),text(l.directions,'muted')));
 const vendors=section('Vendor contacts','Only vendor contacts relevant to your role are shown.');if(!snapshot.vendors.length)vendors.append(empty('Ask your coordinator for a vendor outside your role.'));
 for(const v of snapshot.vendors){const card=group('vendor-card',group('row between',el('h3','',v.name),badge(v.status,v.status==='onsite'?'green':'')),text(`${v.category} · ${teamName(v.team_id)}`,'small muted'),text(`${v.contact_name} · ${v.contact_phone}`));if(has('vendors:team'))card.append(button(v.status==='onsite'?'Mark completed':'Confirm onsite',()=>command({type:'vendor_status',vendor_id:v.id,status:v.status==='onsite'?'complete':'onsite'}),'small-button'));vendors.append(card);}main.append(s,vendors);
}
function knowledge():void{
 const s=section('Knowledge','Approved text sources, versioned and scoped by team. Uploaded text is reference data, never agent authority.');const query=field('Search approved documents');const results=el('div');s.append(group('search-row',query.wrap,button('Search',async()=>{const reply=await api<{items:Dict[]}>(`/api/knowledge?q=${encodeURIComponent(query.input.value)}`);results.replaceChildren();for(const hit of reply.items)results.append(referenceCard(hit));if(!reply.items.length)results.append(empty('No verified answer found. Ask the coordinator.'));})),results);
 if(coordinator()){
  const title=field('Document title');const source=field('Source filename or reference');const content=area('Document text (UTF-8 text or Markdown, up to 60,000 characters)');const file=field('Import a text file','','file');file.input.accept='.txt,.md,text/plain,text/markdown';
  file.input.addEventListener('change',()=>{const f=file.input.files?.[0];if(f){if(f.size>60000){announce('File exceeds 60 KB.',true);return;}source.input.value=f.name;void f.text().then(t=>{content.input.value=t;});}});
  const audience=selectField('Visibility',[{id:'',name:'All enrolled helpers'},...snapshot.teams]);const details=el('details','form-card');details.append(el('summary','','Add a reference document'),title.wrap,source.wrap,file.wrap,content.wrap,audience.wrap,button('Save as unapproved draft',()=>command({type:'add_knowledge',title:title.input.value,source_name:source.input.value,text:content.input.value,audience_team_ids:audience.input.value?[audience.input.value]:[]}),'primary'));s.append(details);
 }
 for(const d of snapshot.knowledge){const card=group('knowledge-card',group('row between',el('h3','',d.title),badge(d.status,d.status==='approved'?'green':'warning')),text(`${d.source_name} · revision ${d.revision}${d.verified_at?' · reviewed '+time(d.verified_at):''}`,'small muted'));
 if(d.text!==null){const detail=el('details');detail.append(el('summary','','Review source text'),el('pre','source-text',d.text));card.append(detail);}
 if(coordinator()){const actions=group('actions');if(d.status==='draft')actions.append(button('Approve for retrieval',async()=>{if(confirm('Confirm you reviewed this source and its audience? Text will become searchable, but cannot execute agent actions.'))await command({type:'review_knowledge',document_id:d.id,decision:'approve'});},'small-button'));if(d.status!=='retired')actions.append(button('Retire',()=>command({type:'review_knowledge',document_id:d.id,decision:'retire'}),'small-button'));card.append(actions);}s.append(card);
 }main.append(s);
}
function referenceCard(hit:Dict):HTMLElement{return group('reference-card',text(String(hit.excerpt||'')),text(`${hit.source} · r${hit.revision} · line ${hit.line}`,'small muted'),badge('Reference, not instructions'));}
function auditScreen():void{
 const s=section('Audit trail','Operational commands and delivery outcomes. This is an application audit log, not a tamper-proof forensic ledger.');s.append(text('Loading…','muted'));main.append(s);
 void api<{items:Dict[]}>('/api/audit').then(r=>{s.replaceChildren(el('h2','','Audit trail'));for(const e of r.items){const details=el('details','audit-row');details.append(el('summary','',`${time(String(e.created_at))} · ${e.event_type} · ${e.actor_id}`),el('pre','source-text',JSON.stringify(e.detail,null,2)));s.append(details);}}).catch(e=>announce(errorText(e),true));
}
function setup():void{
 const s=section('Setup & imports','Create the operating roster before inviting helpers. Every write is permissioned and audited.');
 if(snapshot.wedding.status!=='archived')s.append(button(snapshot.wedding.status==='live'?'Pause automatic task reminders':'Activate event-day task reminders',async()=>{const target=snapshot.wedding.status==='live'?'draft':'live';if(confirm(target==='live'?'Activate task reminders using the current clock, verified roster and schedule?':'Pause automatic task reminder generation? Already queued messages and direct reports are not paused.'))await command({type:'set_wedding_status',status:target});},'primary'));

 const createForm=(title:string,fields:HTMLElement[],action:()=>Promise<void>)=>{const d=el('details','form-card');d.append(el('summary','',title),...fields,button('Create',action,'primary'));s.append(d);};
 const team=field('Team name');createForm('Create a team',[team.wrap],()=>command({type:'create_team',name:team.input.value}));
 const name=field('Helper name');const role=selectField('Role',['helper','registration','usher','photographer','family_liaison','banquet','mc','av','transport','team_lead','coordinator','couple'].map(r=>({id:r,name:r.replaceAll('_',' ')})));const teamSelect=selectField('Team',snapshot.teams);
 createForm('Create a helper membership',[name.wrap,role.wrap,teamSelect.wrap],()=>command({type:'create_member',name:name.input.value,roles:[role.input.value],team_ids:[teamSelect.input.value]}));
 const lname=field('Location name');const directions=area('Directions');createForm('Create a location',[lname.wrap,directions.wrap],()=>command({type:'create_location',name:lname.input.value,directions:directions.input.value,x:50,y:50}));
 const label=field('Table label');const cap=field('Capacity','10','number');const loc=selectField('Location',snapshot.locations);createForm('Create a seating table',[label.wrap,cap.wrap,loc.wrap],()=>command({type:'create_table',label:label.input.value,capacity:Number(cap.input.value),location_id:loc.input.value,x:50,y:50}));
 const ttitle=field('Task title');const instructions=area('Instructions');const owner=selectField('Owner',snapshot.members.filter(m=>m.active));const tteam=selectField('Team',snapshot.teams);const tloc=selectField('Location',snapshot.locations);const due=field('Due timestamp, including UTC offset',`${snapshot.wedding.event_date}T18:00:00+08:00`);const prerequisite=selectField('Prerequisite',[{id:'',name:'None'},...snapshot.tasks.map(t=>({id:t.id,name:t.title}))]);
 createForm('Create a task',[ttitle.wrap,instructions.wrap,owner.wrap,tteam.wrap,tloc.wrap,due.wrap,prerequisite.wrap],()=>command({type:'create_task',title:ttitle.input.value,instructions:instructions.input.value,owner_id:owner.input.value,team_id:tteam.input.value,location_id:tloc.input.value,due_at:due.input.value,depends_on_ids:prerequisite.input.value?[prerequisite.input.value]:[]}));
 const ititle=field('Activity title');const istart=field('Start timestamp, including UTC offset',`${snapshot.wedding.event_date}T21:00:00+08:00`);const duration=field('Duration (minutes)','15','number');const iteam=selectField('Responsible team',snapshot.teams);const iloc=selectField('Location',snapshot.locations);const ipre=selectField('Starts after',[{id:'',name:'None'},...snapshot.timeline.map(t=>({id:t.id,name:t.title}))]);const latest=field('Hard latest end (optional, include UTC offset)');
 createForm('Create a run-of-show activity',[ititle.wrap,istart.wrap,duration.wrap,iteam.wrap,iloc.wrap,ipre.wrap,latest.wrap],()=>command({type:'create_timeline_item',title:ititle.input.value,starts_at:istart.input.value,duration_minutes:Number(duration.input.value),team_ids:[iteam.input.value],location_id:iloc.input.value,depends_on_ids:ipre.input.value?[ipre.input.value]:[],latest_end:latest.input.value||null}));
 const vn=field('Vendor name');const vc=field('Category');const person=field('Contact person');const phone=field('Contact phone');const vteam=selectField('Responsible team',snapshot.teams);const expected=field('Expected arrival, including UTC offset',`${snapshot.wedding.event_date}T16:00:00+08:00`);createForm('Create a vendor',[vn.wrap,vc.wrap,person.wrap,phone.wrap,vteam.wrap,expected.wrap],()=>command({type:'create_vendor',name:vn.input.value,category:vc.input.value,contact_name:person.input.value,contact_phone:phone.input.value,team_id:vteam.input.value,expected_at:expected.input.value}));
 const csv=area('CSV: name,table,rsvp,dietary','name,table,rsvp\nExample Guest,19,yes');const upload=field('Load CSV file','','file');upload.input.accept='.csv,text/csv';upload.input.addEventListener('change',()=>{const f=upload.input.files?.[0];if(f&&f.size<200000)void f.text().then(t=>{csv.input.value=t;});});const preview=el('div');
 const batch=el('details','form-card');batch.append(el('summary','','Preview a guest import'),text('Imports add new guests; they do not silently overwrite existing rows. The seeded demo tables are full. Create a spare table first.','small muted'),upload.wrap,csv.wrap,button('Validate & preview',async()=>{const r=await api<Preview>('/api/import/guests',{csv:csv.input.value});preview.replaceChildren(text(`${r.count} guests · ${r.error_count} validation issues`));for(const e of r.errors)preview.append(text(e,'error-text small'));for(const x of r.sample)preview.append(text(`${x.name} · ${x.table_id} · ${x.rsvp}`,'small'));if(!r.error_count)preview.append(button('Confirm import',()=>command({type:'apply_guest_import',import_id:r.id}),'primary'));}),preview);s.append(batch);
 const download=el('a','button secondary','Export guest seating CSV');download.href='/api/export/guests.csv';download.download='wedding-guests.csv';s.append(group('actions',download,button('Archive wedding',async()=>{if(confirm('Archive this wedding? The application becomes read-only. This cannot be undone from this interface. Export first.'))await command({type:'set_wedding_status',status:'archived'});},'danger-button')));
 main.append(s);
}
async function ask(message:string):Promise<void>{
 chatLog.append(group('chat-message from-user',text(message)));const pending=group('chat-message',text('Checking…','muted'));chatLog.append(pending);chatLog.scrollTop=chatLog.scrollHeight;
 try{const result=await api<ChatReply>('/api/chat',{text:message});pending.replaceChildren(text(result.message),text(`${result.engine.replaceAll('_',' ')} · state checked ${time(result.as_of)}`,'small muted'));
 if(result.draft){const draft=result.draft;const confirmButton=button('Confirm this interpretation',async()=>{await api('/api/confirm',{draft_id:draft.id});confirmButton.remove();pending.append(badge('Report recorded','green'));await refresh(true);},'primary');pending.append(text(draft.summary,'draft-summary'),confirmButton);}
 for(const item of result.data||[]){if(result.kind==='knowledge')pending.append(referenceCard(item));else if(result.kind==='tasks')pending.append(group('chat-result',el('strong','',String(item.title)),text(`${time(String(item.due_at))} · ${item.state}`,'small'),text(String(item.instructions||''),'small muted')));else if(result.kind==='guests')pending.append(text(`${item.name} · Table ${item.table||'unassigned'} · ${item.attendance}`));else if(result.kind==='family')pending.append(text(`${item.name}: ${item.attendance}`));else if(result.kind==='vendors')pending.append(text(`${item.name} · ${item.contact_name} · ${item.contact_phone}`));else pending.append(text(String(item.name||'Table '+item.label)+' · '+String(item.directions||item.location_id||'')));}
 }catch(e){pending.replaceChildren(text(errorText(e),'error-text'));}chatLog.scrollTop=chatLog.scrollHeight;
}

setInterval(()=>{if(!snapshot||!csrf||polling||document.hidden)return;polling=true;void refresh(false).finally(()=>{polling=false;});},8000);
window.addEventListener('online',()=>{if(snapshot)void refresh(true).catch(e=>announce(errorText(e),true));});
window.addEventListener('offline',()=>{healthy=false;if(snapshot)renderHeader();});
window.addEventListener('visibilitychange',()=>{if(!document.hidden&&snapshot&&Date.now()-lastRefresh>15000)void refresh(false);});
void boot();

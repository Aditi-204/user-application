import React, { useEffect, useRef, useState } from 'react';
import { Activity, ArrowDownToLine, ArrowRight, Camera, Check, CheckCircle2, CircleHelp, Clock3, Eye, EyeOff, Filter, LayoutDashboard, LockKeyhole, LogOut, Moon, ShieldCheck, Sparkles, Sun, UserRound, Users, X } from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
const initialUser = JSON.parse(localStorage.getItem('accessdesk_user') || 'null');
const initialToken = localStorage.getItem('accessdesk_token');
const dateText = (v) => new Date(v).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
const todayLabel = new Date().toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).toUpperCase();
const indiaGreeting = () => { const hour = Number(new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', hourCycle: 'h23' }).format(new Date())); return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'; };
const title = (s='') => s.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());

function App() {
  const [token, setToken] = useState(initialToken);
  const [user, setUser] = useState(initialUser);
  const userPreview = import.meta.env.DEV && new URLSearchParams(window.location.search).get('preview') === 'user';
  const [theme, setTheme] = useState(() => localStorage.getItem('accessdesk_theme') || 'light');
  const [mode, setMode] = useState('login');
  const [adminMode, setAdminMode] = useState(false);
  const [tab, setTab] = useState('Overview');
  const [users, setUsers] = useState([]);
  const [events, setEvents] = useState([]);
  const [stats, setStats] = useState({ pending: 0, approved: 0, rejected: 0, logins: 0 });
  const [summary, setSummary] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [doorOpening, setDoorOpening] = useState(false);
  const [showAdminProfile, setShowAdminProfile] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);

  async function api(path, options={}) {
    const response = await fetch(API + path, { ...options, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers } });
    const data = response.status === 204 ? null : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data?.detail || 'Something went wrong. Please try again.');
    return data;
  }
  function signOut() { localStorage.removeItem('accessdesk_token'); localStorage.removeItem('accessdesk_user'); setToken(null); setUser(null); setAdminMode(false); }
  async function loadDashboard() {
    try {
      const [s, u, e, ai] = await Promise.all([api('/admin/overview'), api('/admin/users'), api('/admin/activity'), api('/admin/ai-summary')]);
      setStats(s); setUsers(u); setEvents(e); setSummary(ai.summary);
    } catch (e) { setNotice(e.message); }
  }
  useEffect(() => {
    if (!token || user?.role !== 'admin') return;
    loadDashboard();
    const refresh = window.setInterval(loadDashboard, 15000);
    return () => window.clearInterval(refresh);
  }, [token, user]);
  useEffect(() => { if (notice) { const t = setTimeout(() => setNotice(''), 4000); return () => clearTimeout(t); } }, [notice]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('accessdesk_theme', theme);
  }, [theme]);
  const toggleTheme = () => setTheme(current => current === 'dark' ? 'light' : 'dark');

  async function submitAuth(e) {
    e.preventDefault(); setBusy(true); setNotice('');
    const form = new FormData(e.currentTarget);
    try {
      if (mode === 'register') {
        const result = await api('/auth/register', { method: 'POST', body: JSON.stringify({ name: form.get('name'), email: form.get('email'), password: form.get('password') }) });
        setNotice(result.message); setMode('login');
      } else {
        const result = await api('/auth/login', { method: 'POST', body: JSON.stringify({ email: form.get('email'), password: form.get('password'), admin: adminMode }) });
        if (adminMode && result.user.role !== 'admin') throw new Error('This account does not have administrator access.');
        if (!adminMode && result.user.role === 'admin') throw new Error('Use the administrator sign-in option for this account.');
        localStorage.setItem('accessdesk_token', result.token); localStorage.setItem('accessdesk_user', JSON.stringify(result.user));
        const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (!reducedMotion) setDoorOpening(true);
        setToken(result.token); setUser(result.user); setNotice('');
        if (!reducedMotion) await new Promise(resolve => setTimeout(resolve, 1150));
        setDoorOpening(false);
      }
    } catch (err) { setNotice(err.message); } finally { setBusy(false); }
  }
  async function decide(id, decision) { try { await api(`/admin/users/${id}/${decision}`, { method: 'POST' }); await loadDashboard(); setNotice(`Registration ${decision}d.`); } catch (e) { setNotice(e.message); } }
  function openUserActivity(selected) { setSelectedUser(selected); setTab('User activity'); }

  if ((!token || !user) && userPreview) return <UserHome user={{id:'preview-user',name:'Avery Morgan',email:'avery.morgan@example.com',role:'user',status:'approved'}} api={api} signOut={()=>{window.location.href='/';}} notice={notice} setNotice={setNotice} theme={theme} toggleTheme={toggleTheme} preview />;
  const authProps = { mode, setMode, adminMode, setAdminMode, notice, busy, onSubmit: submitAuth, theme, toggleTheme };
  if (!token || !user) return <Auth {...authProps} />;
  if (user.role !== 'admin') return <DoorTransition active={doorOpening} authProps={authProps}><UserHome user={user} api={api} signOut={signOut} notice={notice} setNotice={setNotice} theme={theme} toggleTheme={toggleTheme} /></DoorTransition>;
  const pending = users.filter(u => u.status === 'pending');
  return <DoorTransition active={doorOpening} authProps={authProps}><div className="app-shell">
    <main className="main-area"><header className="topbar"><div className="admin-header-left"><div className="brand"><span className="brand-mark"><ShieldCheck size={20}/></span><span>access<span className="brand-light">desk</span></span><span className="beta">ADMIN</span></div><nav className="admin-top-nav">{[['Overview',LayoutDashboard],['Users',Users],['Activity logs',Activity]].map(([name,Icon])=><button key={name} onClick={()=>setTab(name)} className={tab===name||tab==='User activity'&&name==='Activity logs'?'selected':''}><Icon size={16}/><span>{name==='Activity logs'?'Activity':name}</span>{name==='Users'&&pending.length>0&&<b>{pending.length}</b>}</button>)}</nav></div><div className="top-actions"><ThemeButton theme={theme} onToggle={toggleTheme}/><button className="admin-profile-trigger" aria-label="Open administrator profile" title="Administrator profile" onClick={()=>setShowAdminProfile(true)}><ProfileAvatar name={user.name} photo={user.avatar_data} size="small"/></button><button className="icon-btn" title="Sign out" aria-label="Sign out" onClick={signOut}><LogOut size={17}/></button></div></header>
      <section className="page-content"><div className="page-heading"><div><p className="eyebrow">{todayLabel}</p><h1>{tab === 'Overview' ? `${indiaGreeting()}, ` : ''}{tab === 'Overview' && <em>{user.name.split(' ')[0]}</em>}{tab !== 'Overview' && tab}</h1><p className="subheading">{tab==='Overview'?'Here’s what’s happening with your workspace today.':tab==='Users'?'Manage access requests and account status.':tab==='User activity'&&selectedUser?`Full account history for ${selectedUser.name}.`:'A record of recent account and profile events.'}</p></div><button className="button button-outline"><ArrowDownToLine size={16}/> Export report</button></div>
      {tab==='Overview'&&<><div className="stats-grid"><Stat label="Total users" value={stats.approved} note="Approved accounts" trend="Active" icon={Users} color="violet"/><Stat label="Pending approvals" value={stats.pending} note="Awaiting your review" trend={stats.pending?'Needs attention':'All clear'} icon={Clock3} color="amber"/><Stat label="Total logins" value={stats.logins} note="All-time successful logins" trend="Tracked" icon={LockKeyhole} color="blue"/><Stat label="Profile updates" value={events.filter(x=>x.action==='profile_updated').length} note="In recent activity" trend="This period" icon={Activity} color="green"/></div>
      <section className="panel full-table admin-table-section"><div className="panel-head"><div><h2>Registration requests <span className="count-pill">{pending.length}</span></h2><p>Review users waiting for access to the workspace</p></div></div><div className="table-wrap"><table><thead><tr><th>USER</th><th>REQUESTED</th><th>STATUS</th><th className="align-right">REVIEW</th></tr></thead><tbody>{pending.map(u=><tr key={u.id}><td><PersonButton user={u} onClick={openUserActivity}/></td><td>{dateText(u.created_at)}</td><td><Status status={u.status}/></td><td className="align-right"><button className="mini-action approve" onClick={()=>decide(u.id,'approve')}><Check size={14}/> Accept</button><button className="mini-action reject" onClick={()=>decide(u.id,'reject')}><X size={14}/> Reject</button></td></tr>)}{!pending.length&&<EmptyRow text="No pending requests. You're all caught up." cols={4}/>}</tbody></table></div></section>
      <section className="panel full-table admin-table-section"><div className="panel-head"><div><h2>User activity <span className="count-pill">{events.length}</span></h2><p>Account creation, profile changes, deletions, and sign-ins. Select a user to see their history.</p></div><button className="text-button" onClick={()=>setTab('Activity logs')}>View all activity <ArrowRight size={15}/></button></div><ActivityTable items={events.slice(0,10)} onSelectUser={openUserActivity}/></section>
      <section className="insight-card"><div className="insight-icon"><Sparkles size={20}/></div><div><div className="insight-title">AI workspace insight <span>NEW</span></div><p>{summary || 'Gathering activity insights…'}</p></div><button className="insight-link" onClick={()=>setTab('Activity logs')}>Explore activity <ArrowRight size={15}/></button></section></>}
      {tab==='Users'&&<section className="panel full-table"><div className="panel-head"><div><h2>All users <span className="count-pill">{users.length}</span></h2><p>Select a user to see their activity history</p></div><div className="table-tools"><button className="button button-outline"><ArrowDownToLine size={15}/> Export</button></div></div><UserTable users={users} decide={decide} onSelectUser={openUserActivity}/></section>}
      {tab==='Activity logs'&&<section className="panel full-table"><div className="panel-head"><div><h2>Activity log <span className="count-pill">{events.length}</span></h2><p>Account creations, approvals, sign-ins, profile changes, and deletions</p></div><div className="table-tools"><button className="button button-outline"><Filter size={15}/> Filter</button><button className="button button-outline"><ArrowDownToLine size={15}/> Export</button></div></div><ActivityTable items={events} onSelectUser={openUserActivity}/></section>}
      {tab==='User activity'&&selectedUser&&<section className="panel full-table"><div className="panel-head user-activity-heading"><div><h2>Activity for {selectedUser.name}</h2><p>{selectedUser.email} · {events.filter(e=>e.target_id===selectedUser.id||e.actor_id===selectedUser.id).length} recorded events</p></div><button className="button button-outline" onClick={()=>setTab('Activity logs')}><ArrowRight className="back-arrow" size={15}/> Back to activity</button></div><ActivityTable items={events.filter(e=>e.target_id===selectedUser.id||e.actor_id===selectedUser.id)} onSelectUser={openUserActivity}/></section>}
      <footer className="footer">© {new Date().getFullYear()} AccessDesk <span>•</span> Built for secure, thoughtful access management <a>Privacy</a><a>Support</a></footer>
      </section></main>{showAdminProfile&&<AdminProfileModal user={user} api={api} onClose={()=>setShowAdminProfile(false)} onSave={updated=>{setUser(updated);localStorage.setItem('accessdesk_user',JSON.stringify(updated));setShowAdminProfile(false);setNotice('Administrator profile updated.');}}/>}{notice&&<div className="toast"><CheckCircle2 size={17}/>{notice}<button onClick={()=>setNotice('')}><X size={15}/></button></div>}
  </div></DoorTransition>;
}

function DoorTransition({active,authProps,children}) { return <div className="door-stage">{children}{active&&<div className="door-curtain" aria-hidden="true"><Auth {...authProps} doorOpening transitionOnly /></div>}</div>; }

function AdminProfileModal({user,api,onClose,onSave}) {
  const [name,setName]=useState(user.name);
  const [email,setEmail]=useState(user.email);
  const [photo,setPhoto]=useState(user.avatar_data||null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const input=useRef(null);
  function selectPhoto(event) {
    const file=event.target.files?.[0];
    if(!file)return;
    if(!['image/png','image/jpeg','image/webp'].includes(file.type)){setError('Choose a PNG, JPEG, or WebP image.');return;}
    if(file.size>1024*1024){setError('Profile photos must be 1 MB or smaller.');return;}
    const reader=new FileReader();
    reader.onload=()=>setPhoto(typeof reader.result==='string'?reader.result:null);
    reader.onerror=()=>setError('Could not read that image. Please try another file.');
    reader.readAsDataURL(file);
  }
  async function save(event) {
    event.preventDefault();setBusy(true);setError('');
    try{const updated=await api('/profile',{method:'PATCH',body:JSON.stringify({name,email,avatar_data:photo})});onSave(updated);}
    catch(error){setError(error.message);setBusy(false);}
  }
  return <div className="modal-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)onClose();}}><section className="admin-profile-modal" role="dialog" aria-modal="true" aria-labelledby="admin-profile-title"><div className="modal-heading"><div><span className="eyebrow">ADMINISTRATOR</span><h2 id="admin-profile-title">Your profile</h2></div><button className="icon-btn" onClick={onClose} aria-label="Close profile"><X size={19}/></button></div><form onSubmit={save}><div className="admin-photo-editor"><ProfileAvatar name={name} photo={photo}/><div><b>Profile photo</b><p>PNG, JPEG, or WebP · up to 1 MB</p><button type="button" className="button button-outline" onClick={()=>input.current?.click()}><Camera size={15}/> Change photo</button>{photo&&<button type="button" className="photo-remove" onClick={()=>setPhoto(null)}>Remove</button>}<input ref={input} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp" onChange={selectPhoto}/></div></div><label>Full name<div className="input-wrap"><UserRound size={16}/><input value={name} onChange={event=>setName(event.target.value)} required minLength="2"/></div></label><label>Email address<div className="input-wrap"><span className="at-icon">@</span><input type="email" value={email} disabled/></div></label>{error&&<div className="inline-notice">{error}</div>}<div className="modal-actions"><button className="button button-outline" type="button" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}>{busy?'Saving…':'Save profile'}</button></div></form></section></div>;
}

function Auth({mode,setMode,adminMode,setAdminMode,notice,busy,onSubmit,theme,toggleTheme,doorOpening=false,transitionOnly=false}) { const [showPassword,setShowPassword]=useState(false); return <div className={`auth-page${doorOpening?' door-opening':''}${transitionOnly?' transition-only':''}`}><div className="auth-left"><div className="auth-brand"><span className="brand-mark"><ShieldCheck size={20}/></span><span>access<span className="brand-light">desk</span></span></div><div className="auth-pitch"><div className="hero-badge"><span/> ACCESS, WITH INTENTION</div><h1>A safer space<br/>starts <em>here.</em></h1><p>Thoughtful access management for teams that value trust, transparency, and people.</p><div className="hero-graphic"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="hero-center"><ShieldCheck size={34}/></div><span className="sparkle s1">✦</span><span className="sparkle s2">✧</span></div></div><div className="auth-left-footer"><span>DESIGNED FOR PEOPLE. BUILT FOR TRUST.</span><span><i/> SECURE BY DESIGN</span></div></div>
  <div className="auth-right"><div className="auth-top"><ThemeButton theme={theme} onToggle={toggleTheme}/><span>Already have access?</span><button onClick={()=>{setMode(mode==='login'?'register':'login');setAdminMode(false)}}>{mode==='login'?'Create an account':'Sign in'}</button></div><div className="auth-form-wrap"><div className="mobile-brand"><span className="brand-mark"><ShieldCheck size={18}/></span>accessdesk</div><div className="form-kicker">{adminMode?'ADMINISTRATOR PORTAL':'YOUR WORKSPACE AWAITS'}</div><h2>{mode==='register'?'Create your account':adminMode?'Welcome, administrator':'Welcome back'}</h2><p className="form-intro">{mode==='register'?'Request access to your team’s workspace.':'Enter your details to access your workspace.'}</p><div className="auth-switch"><button className={!adminMode?'active':''} onClick={()=>setAdminMode(false)}><UserRound size={16}/> User sign in</button><button className={adminMode?'active':''} onClick={()=>setAdminMode(true)}><ShieldCheck size={16}/> Admin sign in</button></div><form onSubmit={onSubmit}>{mode==='register'&&<label>Full name<div className="input-wrap"><UserRound size={16}/><input name="name" placeholder="e.g. Alex Morgan" required minLength="2"/></div></label>}<label>Email address<div className="input-wrap"><span className="at-icon">@</span><input name="email" type="email" placeholder="you@company.com" required/></div></label><label>Password<div className="input-wrap"><LockKeyhole size={15}/><input name="password" type={showPassword?'text':'password'} placeholder={mode==='register'?'At least 8 characters':'Enter your password'} required minLength={mode==='register'?8:1}/><button type="button" className="password-visibility" aria-label={showPassword?'Hide password':'Show password'} title={showPassword?'Hide password':'Show password'} onClick={()=>setShowPassword(value=>!value)}>{showPassword?<EyeOff size={17}/>:<Eye size={17}/>}</button></div></label>{mode==='login'&&<div className="form-options"><label className="remember"><input type="checkbox"/> Remember me</label><button type="button" className="link-button">Forgot password?</button></div>}<button className="button primary submit-btn" disabled={busy}>{busy?'Please wait…':mode==='register'?'Request access':'Sign in'}<ArrowRight size={16}/></button></form>{notice&&<div className="inline-notice">{notice}</div>}<div className="auth-divider"><span/> OR <span/></div><div className="approval-note"><span><Clock3 size={16}/></span><p><b>New to the workspace?</b><br/>Account requests are reviewed by an administrator before access is granted.</p></div><div className="auth-bottom"><span>© {new Date().getFullYear()} AccessDesk</span><button><CircleHelp size={14}/> Help center</button></div></div></div></div> }

function UserHome({user,api,signOut,notice,setNotice,theme,toggleTheme,preview=false}) {
  const [name,setName]=useState(user.name);
  const [email,setEmail]=useState(user.email);
  const [avatarData,setAvatarData]=useState(user.avatar_data || null);
  const [busy,setBusy]=useState(false);
  const photoInput=useRef(null);

  function choosePhoto(event) {
    const file=event.target.files?.[0];
    if (!file) return;
    if (!['image/png','image/jpeg','image/webp'].includes(file.type)) { setNotice('Choose a PNG, JPEG, or WebP image.'); event.target.value=''; return; }
    if (file.size>1024*1024) { setNotice('Profile photos must be 1 MB or smaller.'); event.target.value=''; return; }
    const reader=new FileReader();
    reader.onload=()=>setAvatarData(typeof reader.result==='string'?reader.result:null);
    reader.onerror=()=>setNotice('Could not read that image. Please try another file.');
    reader.readAsDataURL(file);
  }

  async function save(event) {
    event.preventDefault();
    if (preview) { setNotice('Preview mode — profile changes are not saved.'); return; }
    setBusy(true);
    try {
      const updated=await api('/profile',{method:'PATCH',body:JSON.stringify({name,email,avatar_data:avatarData})});
      localStorage.setItem('accessdesk_user',JSON.stringify(updated));
      setName(updated.name); setEmail(updated.email);
      setNotice('Profile updated.');
    } catch (error) { setNotice(error.message); }
    finally { setBusy(false); }
  }

  async function del() {
    if (preview) { setNotice('Preview mode — account actions are disabled.'); return; }
    if (!window.confirm('Delete your account and profile? This cannot be undone.')) return;
    try { await api('/profile',{method:'DELETE'}); signOut(); }
    catch (error) { setNotice(error.message); }
  }

  return <div className="user-page">
    <header className="user-top"><div className="auth-brand"><span className="brand-mark"><ShieldCheck size={20}/></span><span>access<span className="brand-light">desk</span></span></div><div className="user-actions">{preview&&<span className="preview-pill">DEMO PREVIEW</span>}<ProfileAvatar name={name} photo={avatarData} size="small"/><ThemeButton theme={theme} onToggle={toggleTheme}/><button className="button button-outline" onClick={signOut}><LogOut size={16}/>{preview?'Back to sign in':'Sign out'}</button></div></header>
    <main className="user-content">
      <div className="member-identity"><ProfileAvatar name={name} photo={avatarData}/><div><div className="hero-badge"><span/> MEMBER WORKSPACE</div><h1>Welcome, <em>{name.split(' ')[0]}.</em></h1><p>Your account is approved and you have access to the workspace.</p></div></div>
      <section className="panel profile-card"><div className="panel-head"><div><h2>Your profile</h2><p>Update your photo, name, and email associated with your account.</p></div><span className="status approved"><CheckCircle2 size={13}/> Approved</span></div>
        <form onSubmit={save} className="profile-form">
          <div className="avatar-editor"><ProfileAvatar name={name} photo={avatarData}/><div className="avatar-editor-copy"><b>Profile photo</b><p>PNG, JPEG, or WebP · up to 1 MB</p><div className="avatar-editor-actions"><button type="button" className="button button-outline" onClick={()=>photoInput.current?.click()}><Camera size={15}/> Choose photo</button>{avatarData&&<button type="button" className="photo-remove" onClick={()=>setAvatarData(null)}>Remove photo</button>}</div><input ref={photoInput} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp" onChange={choosePhoto}/></div></div>
          <label>Full name<div className="input-wrap"><UserRound size={16}/><input value={name} onChange={event=>setName(event.target.value)} required minLength="2"/></div></label>
          <label>Email address<div className="input-wrap"><span className="at-icon">@</span><input type="email" value={email} onChange={event=>setEmail(event.target.value)} required/></div></label>
          <button className="button primary" disabled={busy}>{busy?'Saving…':preview?'Preview changes':'Save profile'} <ArrowRight size={15}/></button>
        </form>
        {!preview&&<button className="delete-link" onClick={del}>Delete my profile</button>}
      </section>{notice&&<div className="inline-notice">{notice}</div>}
    </main>
  </div>;
}

function ProfileAvatar({name,photo,size=''}) {
  const initials=(name||'User').split(' ').map(part=>part[0]).slice(0,2).join('').toUpperCase();
  return <span className={`member-avatar ${size}`}>{photo?<img src={photo} alt={`${name}'s profile`}/>:initials}</span>;
}
function ThemeButton({theme,onToggle}) { const dark=theme==='dark'; const Icon=dark?Sun:Moon; return <button className="theme-toggle" type="button" onClick={onToggle} aria-label={`Switch to ${dark?'light':'dark'} mode`} title={`Switch to ${dark?'light':'dark'} mode`}><Icon size={16}/><span>{dark?'Light':'Dark'} mode</span></button>; }
function Stat({label,value,note,trend,icon:Icon,color}){return <article className="stat-card"><div className="stat-top"><span>{label}</span><span className={`stat-icon ${color}`}><Icon size={17}/></span></div><div className="stat-number">{value.toLocaleString()}</div><div className="stat-bottom"><span>{note}</span><span className={`trend ${color}`}>{trend}</span></div></article>}
function Person({name,email}){return <div className="person"><span className={`avatar color-${(name||'A').charCodeAt(0)%5}`}>{(name||'U').split(' ').map(x=>x[0]).slice(0,2).join('').toUpperCase()}</span><span><b>{name}</b><small>{email}</small></span></div>}
function PersonButton({user,onClick}){return <button type="button" className="person-link" onClick={()=>onClick(user)} title={`View ${user.name}'s activity`}><Person name={user.name} email={user.email}/><ArrowRight size={14}/></button>}
function Status({status}){return <span className={`status ${status}`}><i/>{title(status)}</span>}
function activityLabel(action){return ({account_created:'Account created',profile_updated:'Profile updated',profile_deleted:'Profile deleted',registration_approved:'Request accepted',registration_rejected:'Request rejected',login:'Signed in'})[action]||title(action)}
function EventBadge({action}){const style=action.includes('login')?'blue':action.includes('profile')?'violet':action.includes('approved')?'green':action.includes('rejected')?'red':'amber';return <span className={`event-badge ${style}`}><Activity size={13}/>{activityLabel(action)}</span>}
function ActivityTable({items,onSelectUser}){return <div className="table-wrap"><table className="activity-table"><thead><tr><th>ACTION</th><th>USER</th><th>WHAT CHANGED</th><th>DATE & TIME (IST)</th></tr></thead><tbody>{items.map(e=>{const selected={id:e.target_id||e.actor_id,name:e.target_name||e.actor_name,email:e.target_email||e.actor_email};return <tr key={e.id}><td><EventBadge action={e.action}/></td><td>{onSelectUser&&selected.id?<PersonButton user={selected} onClick={onSelectUser}/>:<Person name={selected.name} email={selected.email}/>}</td><td className="detail-cell">{e.detail||activityLabel(e.action)}</td><td>{dateText(e.created_at)}</td></tr>})}{!items.length&&<EmptyRow text="No activity has been recorded yet." cols={4}/>}</tbody></table></div>}
function EmptyRow({text,cols}){return <tr><td colSpan={cols} className="empty-row">{text}</td></tr>}
function UserTable({users,decide,onSelectUser}){return <div className="table-wrap"><table><thead><tr><th>USER</th><th>JOINED</th><th>STATUS</th><th className="align-right">ACTIONS</th></tr></thead><tbody>{users.map(u=><tr key={u.id}><td><PersonButton user={u} onClick={onSelectUser}/></td><td>{dateText(u.created_at)}</td><td><Status status={u.status}/></td><td className="align-right">{u.status==='pending'?<><button className="mini-action approve" onClick={()=>decide(u.id,'approve')}><Check size={14}/> Approve</button><button className="mini-action reject" onClick={()=>decide(u.id,'reject')}>Decline</button></>:<span className="muted">—</span>}</td></tr>)}</tbody></table></div>}

export default App;

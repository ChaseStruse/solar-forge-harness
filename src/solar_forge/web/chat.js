'use strict';
const $ = (id) => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('forge-token') || '';
if (token) sessionStorage.setItem('forge-token', token);
history.replaceState(null, '', '/');
let current = null;
let busy = false;
let config = null;

async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST',
    headers: {'Authorization': `Bearer ${token}`, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
    ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Could not reach Forge chat.');
  return result;
}
function feedback(text, error = false) {
  $('feedback').textContent = text;
  $('feedback').className = error ? 'feedback error' : 'feedback';
}
function controls() {
  const unavailable = busy || !config;
  $('send').disabled = unavailable || Boolean(current?.pending_message) || !$('message').value.trim();
  $('new-chat').disabled = unavailable;
  $('message').disabled = unavailable || Boolean(current?.pending_message);
  $('retry').hidden = !current?.pending_message || busy;
  document.querySelectorAll('[data-prompt]').forEach((el) => el.disabled = unavailable);
  document.querySelectorAll('.session').forEach((el) => el.disabled = busy);
}
function render() {
  const messages = current?.messages || [];
  $('welcome').hidden = Boolean(messages.length || current?.pending_message);
  $('chat-title').textContent = current?.title || 'New chat';
  $('model').textContent = `${current?.provider || config.provider} / ${current?.model || config.model}`;
  const container = $('messages');
  container.replaceChildren();
  for (const message of [...messages, ...(current?.pending_message ? [{role: 'user', content: current.pending_message, pending: true}] : [])]) {
    const article = document.createElement('article');
    article.className = `message ${message.role}${message.pending ? ' pending' : ''}`;
    const avatar = document.createElement('div');
    avatar.className = 'avatar'; avatar.textContent = message.role === 'user' ? 'Y' : 'F'; avatar.setAttribute('aria-hidden', 'true');
    const body = document.createElement('div'); body.className = 'message-body';
    const label = document.createElement('div'); label.className = 'message-label'; label.textContent = message.role === 'user' ? 'You' : 'Forge';
    const text = document.createElement('div'); text.className = 'message-text'; text.textContent = message.content;
    body.append(label, text); article.append(avatar, body); container.append(article);
  }
  controls();
  $('scroll-area').scrollTop = $('scroll-area').scrollHeight;
}
async function historyList() {
  const {sessions} = await api('/api/sessions');
  const nav = $('sessions'); nav.replaceChildren();
  if (!sessions.length) {
    const empty = document.createElement('p'); empty.className = 'empty-history'; empty.textContent = 'Your chats will appear here.'; nav.append(empty);
  }
  for (const session of sessions) {
    const button = document.createElement('button'); button.className = `session${session.id === current?.id ? ' active' : ''}`;
    button.textContent = session.title; button.title = session.title; button.disabled = busy;
    button.addEventListener('click', async () => {
      if (busy) return;
      try { current = await api(`/api/session?id=${encodeURIComponent(session.id)}`); render(); await historyList();
        feedback(current.pending_message ? 'This message is waiting for a reply. Retry to continue.' : '');
      } catch (error) { feedback(error.message, true); }
    });
    nav.append(button);
  }
}
async function send(retry = false) {
  if (busy) return;
  const message = $('message').value.trim();
  if (!retry && !message) return;
  busy = true; controls(); feedback('Your model is thinking…');
  try {
    if (!current) current = await api('/api/sessions', {});
    if (!retry) { current.pending_message = message; $('message').value = ''; $('message').style.height = ''; render(); }
    current = await api(retry ? '/api/retry' : '/api/message', retry ? {id: current.id} : {id: current.id, message});
    feedback('');
  } catch (error) {
    // Refresh authoritative state: a failed reply has a saved pending turn;
    // rejected submissions do not, and the unsent draft should remain editable.
    if (current) {
      try { current = await api(`/api/session?id=${encodeURIComponent(current.id)}`); } catch (_) { /* Keep pending turn visible. */ }
    }
    if (!retry && !current?.pending_message) $('message').value = message;
    feedback(error.message, true);
  } finally {
    busy = false; render();
    try { await historyList(); } catch (error) { feedback(error.message, true); }
    if (!current?.pending_message) $('message').focus();
  }
}
$('composer').addEventListener('submit', (event) => { event.preventDefault(); send(); });
$('message').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!$('send').disabled) send(); }
});
$('message').addEventListener('input', () => {
  $('message').style.height = 'auto'; $('message').style.height = `${Math.min($('message').scrollHeight, 180)}px`; controls();
});
$('retry').addEventListener('click', () => send(true));
$('new-chat').addEventListener('click', async () => {
  current = null; $('message').value = ''; feedback(''); render();
  try { await historyList(); } catch (error) { feedback(error.message, true); }
  $('message').focus();
});
document.querySelectorAll('[data-prompt]').forEach((button) => button.addEventListener('click', () => {
  $('message').value = button.dataset.prompt; controls(); $('message').focus();
}));
(async () => {
  try { config = await api('/api/config'); $('project').textContent = config.project; render(); await historyList(); $('message').focus(); }
  catch (error) { feedback(error.message, true); $('message').disabled = true; $('send').disabled = true; }
})();

/* 落地页：创建空间入口。 */

const $ = (s) => document.querySelector(s);
const form = $('#create-form');
const modal = $('#create');
const errEl = $('#create-err');

function openCreate() {
  modal.hidden = false;
  $('#create-name').focus();
}
function closeCreate() {
  modal.hidden = true;
  errEl.textContent = '';
}

for (const id of ['nav-create', 'hero-create', 'bottom-create']) {
  document.getElementById(id)?.addEventListener('click', openCreate);
}
$('#create-close').addEventListener('click', closeCreate);
modal.addEventListener('click', (e) => { if (e.target === modal) closeCreate(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeCreate(); });

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  errEl.textContent = '';
  const name = $('#create-name').value.trim();
  const password = $('#create-password').value;
  const invite = $('#create-invite').value.trim();

  if (password.length < 6) {
    errEl.textContent = '密码至少 6 位';
    return;
  }

  const btn = form.querySelector('button[type="submit"]');
  btn.disabled = true;
  btn.textContent = '创建中…';
  try {
    const res = await fetch('/api/spaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, password, invite }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      errEl.textContent = data.error || '创建失败，稍后再试';
      if (res.status === 403) {
        $('#invite-field').hidden = false;
        $('#create-invite').focus();
      }
      return;
    }
    location.href = '/s/' + data.spaceId;
  } catch {
    errEl.textContent = '网络错误，稍后再试';
  } finally {
    btn.disabled = false;
    btn.textContent = '创建';
  }
});

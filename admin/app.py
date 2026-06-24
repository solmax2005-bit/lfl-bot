import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template_string, request, session, redirect, url_for, jsonify

app = Flask(__name__)
app.secret_key = os.getenv("ADMIN_SECRET_KEY", "lfl-admin-secret-2024")

DB_PATH  = os.getenv("DB_PATH",       os.path.join(os.path.dirname(__file__), "..", "lfl_bot.db"))
LOG_PATH = os.getenv("BOT_LOG_PATH",  os.path.join(os.path.dirname(__file__), "..", "bot.log"))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        total_users   = c.execute("SELECT COUNT(*) FROM free_agents").fetchone()[0]
        active_agents = c.execute("SELECT COUNT(*) FROM free_agents WHERE active=1").fetchone()[0]
        lfl_agents    = c.execute("SELECT COUNT(*) FROM free_agents WHERE lfl_url != ''").fetchone()[0]
        looking       = c.execute("SELECT COUNT(*) FROM free_agents WHERE active=1 AND looking=1").fetchone()[0]

        total_teams   = c.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
        active_teams  = c.execute("SELECT COUNT(*) FROM teams WHERE active=1").fetchone()[0]

        by_position = c.execute(
            "SELECT position, COUNT(*) as cnt FROM free_agents WHERE active=1 GROUP BY position ORDER BY cnt DESC"
        ).fetchall()

        recent_agents = c.execute(
            "SELECT name, position, created_at FROM free_agents ORDER BY created_at DESC LIMIT 5"
        ).fetchall()

        recent_teams = c.execute(
            "SELECT name, league, created_at FROM teams ORDER BY created_at DESC LIMIT 5"
        ).fetchall()

        conn.close()
        return {
            "total_users":   total_users,
            "active_agents": active_agents,
            "lfl_agents":    lfl_agents,
            "looking":       looking,
            "total_teams":   total_teams,
            "active_teams":  active_teams,
            "by_position":   [dict(r) for r in by_position],
            "recent_agents": [dict(r) for r in recent_agents],
            "recent_teams":  [dict(r) for r in recent_teams],
        }
    except Exception as e:
        return {"error": str(e)}


def get_messages(limit=200):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM bot_messages ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return []


def get_logs(lines=200):
    try:
        if not os.path.exists(LOG_PATH):
            return ["Лог-файл не найден: " + LOG_PATH]
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return [l.rstrip() for l in all_lines[-lines:]]
    except Exception as e:
        return [f"Ошибка чтения лога: {e}"]


HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ЛФЛ Агент — Панель</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f1923; color: #ccddef; font-family: 'Segoe UI', sans-serif; min-height: 100vh; }
  .navbar { background: #1a3252; padding: 14px 24px; display: flex; align-items: center; gap: 24px; border-bottom: 2px solid #299dff; }
  .navbar h1 { color: #fff; font-size: 18px; flex: 1; }
  .navbar a { color: #a8bed4; text-decoration: none; font-size: 14px; padding: 6px 14px; border-radius: 6px; transition: background .2s; white-space: nowrap; }
  .navbar a:hover, .navbar a.active { background: #263a50; color: #fff; }
  .navbar .logout { color: #ff6b6b; margin-left: auto; }
  .container { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }

  /* Stats */
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }
  .card { background: #131f2d; border-radius: 10px; padding: 20px; border: 1px solid #263a50; }
  .card .val { font-size: 36px; font-weight: 700; color: #fff; }
  .card .lbl { font-size: 12px; color: #a8bed4; margin-top: 4px; text-transform: uppercase; letter-spacing: .5px; }
  .card.accent .val { color: #299dff; }
  .card.green .val  { color: #4caf50; }
  .card.gold .val   { color: #ffc107; }

  /* Tables */
  .section { background: #131f2d; border-radius: 10px; padding: 20px; margin-bottom: 20px; border: 1px solid #263a50; }
  .section h2 { font-size: 15px; color: #a8bed4; margin-bottom: 14px; text-transform: uppercase; letter-spacing: .5px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; color: #a8bed4; font-weight: 600; padding: 8px 12px; border-bottom: 1px solid #263a50; font-size: 12px; text-transform: uppercase; }
  td { padding: 8px 12px; border-bottom: 1px solid #1a2e44; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #1a2e44; }

  /* Logs */
  .log-box { background: #080e14; border-radius: 8px; padding: 16px; font-family: 'Consolas', monospace; font-size: 12px; line-height: 1.6; max-height: 600px; overflow-y: auto; border: 1px solid #263a50; }
  .log-line { white-space: pre-wrap; word-break: break-all; }
  .log-line.error   { color: #ff6b6b; }
  .log-line.warning { color: #ffc107; }
  .log-line.info    { color: #ccddef; }
  .log-controls { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; }
  .log-controls label { font-size: 13px; color: #a8bed4; }
  .btn { background: #299dff; color: #fff; border: none; padding: 7px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .btn:hover { background: #1a7fd4; }
  .btn.secondary { background: #263a50; }
  .btn.secondary:hover { background: #1a2e44; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .badge.blue { background: #1a3d6b; color: #299dff; }
  .badge.green { background: #1a3d2b; color: #4caf50; }

  /* Login */
  .login-wrap { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .login-box { background: #131f2d; border-radius: 12px; padding: 40px; width: 340px; border: 1px solid #263a50; }
  .login-box h2 { color: #fff; margin-bottom: 24px; font-size: 20px; }
  .login-box input { width: 100%; background: #0f1923; border: 1px solid #263a50; color: #fff; padding: 10px 14px; border-radius: 6px; font-size: 14px; margin-bottom: 14px; outline: none; }
  .login-box input:focus { border-color: #299dff; }
  .login-box button { width: 100%; }
  .error-msg { color: #ff6b6b; font-size: 13px; margin-bottom: 12px; }

  #auto-label { font-size: 12px; color: #4caf50; }
</style>
</head>
<body>

{% if page == 'login' %}
<div class="login-wrap">
  <div class="login-box">
    <h2>⚽ ЛФЛ Агент</h2>
    {% if error %}<div class="error-msg">{{ error }}</div>{% endif %}
    <form method="post">
      <input type="password" name="password" placeholder="Пароль" autofocus>
      <button class="btn" type="submit">Войти</button>
    </form>
  </div>
</div>

{% elif page == 'dashboard' %}
<div class="navbar">
  <h1>⚽ ЛФЛ Агент</h1>
  <a href="/" class="active">Статистика</a>
  <a href="/messages">Сообщения</a>
  <a href="/logs">Логи</a>
  <a href="/logout" class="logout">Выйти</a>
</div>
<div class="container">
  {% if stats.error %}
    <p style="color:#ff6b6b">Ошибка БД: {{ stats.error }}</p>
  {% else %}
  <div class="cards">
    <div class="card accent"><div class="val">{{ stats.total_users }}</div><div class="lbl">Всего пользователей</div></div>
    <div class="card green"><div class="val">{{ stats.active_agents }}</div><div class="lbl">Активных агентов</div></div>
    <div class="card"><div class="val">{{ stats.lfl_agents }}</div><div class="lbl">С профилем lfl.ru</div></div>
    <div class="card gold"><div class="val">{{ stats.looking }}</div><div class="lbl">Ищут команду</div></div>
    <div class="card accent"><div class="val">{{ stats.total_teams }}</div><div class="lbl">Всего команд</div></div>
    <div class="card green"><div class="val">{{ stats.active_teams }}</div><div class="lbl">Активных команд</div></div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
    <div class="section">
      <h2>Агенты по позициям</h2>
      <table>
        <tr><th>Позиция</th><th>Кол-во</th></tr>
        {% for row in stats.by_position %}
        <tr><td>{{ row.position or '—' }}</td><td><span class="badge blue">{{ row.cnt }}</span></td></tr>
        {% endfor %}
      </table>
    </div>

    <div class="section">
      <h2>Последние регистрации</h2>
      <table>
        <tr><th>Имя</th><th>Позиция</th><th>Дата</th></tr>
        {% for a in stats.recent_agents %}
        <tr>
          <td>{{ a.name }}</td>
          <td>{{ a.position or '—' }}</td>
          <td style="color:#a8bed4;font-size:12px">{{ a.created_at[:10] if a.created_at else '—' }}</td>
        </tr>
        {% endfor %}
      </table>
    </div>

    <div class="section">
      <h2>Последние команды</h2>
      <table>
        <tr><th>Команда</th><th>Лига</th><th>Дата</th></tr>
        {% for t in stats.recent_teams %}
        <tr>
          <td>{{ t.name }}</td>
          <td><span class="badge green">{{ t.league }}</span></td>
          <td style="color:#a8bed4;font-size:12px">{{ t.created_at[:10] if t.created_at else '—' }}</td>
        </tr>
        {% endfor %}
      </table>
    </div>
  </div>
  {% endif %}
</div>

{% elif page == 'messages' %}
<div class="navbar">
  <h1>⚽ ЛФЛ Агент</h1>
  <a href="/">Статистика</a>
  <a href="/messages" class="active">Сообщения</a>
  <a href="/logs">Логи</a>
  <a href="/logout" class="logout">Выйти</a>
</div>
<div class="container">
  <div class="section">
    <h2>Переписки пользователей</h2>
    <table>
      <tr><th>Время</th><th>Пользователь</th><th>ID</th><th>Сообщение</th></tr>
      {% for m in messages %}
      <tr>
        <td style="color:#a8bed4;font-size:12px;white-space:nowrap">{{ m.created_at[:16] if m.created_at else '—' }}</td>
        <td>
          {% if m.username %}<span class="badge blue">@{{ m.username }}</span>{% endif %}
          <span style="font-size:13px;color:#ccddef;margin-left:4px">{{ m.full_name or '—' }}</span>
        </td>
        <td style="color:#a8bed4;font-size:12px">{{ m.tg_id }}</td>
        <td style="max-width:400px;word-break:break-word">{{ m.text }}</td>
      </tr>
      {% else %}
      <tr><td colspan="4" style="color:#a8bed4;text-align:center;padding:24px">Сообщений пока нет</td></tr>
      {% endfor %}
    </table>
  </div>
</div>

{% elif page == 'logs' %}
<div class="navbar">
  <h1>⚽ ЛФЛ Агент</h1>
  <a href="/">Статистика</a>
  <a href="/messages">Сообщения</a>
  <a href="/logs" class="active">Логи</a>
  <a href="/logout" class="logout">Выйти</a>
</div>
<div class="container">
  <div class="log-controls">
    <button class="btn secondary" onclick="loadLogs()">🔄 Обновить</button>
    <button class="btn secondary" onclick="toggleAuto()">⏱ Авто</button>
    <span id="auto-label"></span>
    <label>Строк: <select id="lines-select" onchange="loadLogs()" style="background:#0f1923;color:#fff;border:1px solid #263a50;border-radius:4px;padding:4px">
      <option value="100">100</option>
      <option value="200" selected>200</option>
      <option value="500">500</option>
    </select></label>
    <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
      <input type="checkbox" id="errors-only" onchange="loadLogs()"> Только ошибки
    </label>
    <button class="btn" onclick="scrollBottom()">↓ Конец</button>
  </div>
  <div class="log-box" id="log-box">Загрузка...</div>
</div>
<script>
let autoTimer = null;
function loadLogs() {
  const n = document.getElementById('lines-select').value;
  const errOnly = document.getElementById('errors-only').checked;
  fetch('/api/logs?lines=' + n)
    .then(r => r.json())
    .then(data => {
      const box = document.getElementById('log-box');
      let lines = data.lines;
      if (errOnly) lines = lines.filter(l => l.includes('ERROR') || l.includes('Traceback') || l.includes('Exception'));
      if (!lines.length && errOnly) lines = ['✅ Ошибок не найдено'];
      box.innerHTML = lines.map(l => {
        let cls = 'info';
        if (l.includes('[ERROR]') || l.includes('ERROR') || l.includes('Traceback')) cls = 'error';
        else if (l.includes('[WARNING]') || l.includes('WARNING')) cls = 'warning';
        return '<div class="log-line ' + cls + '">' + escHtml(l) + '</div>';
      }).join('');
    });
}
function scrollBottom() {
  const box = document.getElementById('log-box');
  box.scrollTop = box.scrollHeight;
}
function toggleAuto() {
  if (autoTimer) {
    clearInterval(autoTimer);
    autoTimer = null;
    document.getElementById('auto-label').textContent = '';
  } else {
    autoTimer = setInterval(() => { loadLogs(); scrollBottom(); }, 5000);
    document.getElementById('auto-label').textContent = 'Авто-обновление каждые 5 сек';
  }
}
function escHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
loadLogs();
</script>
{% endif %}

</body>
</html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        error = "Неверный пароль"
    return render_template_string(HTML, page="login", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    return render_template_string(HTML, page="dashboard", stats=get_stats())


@app.route("/messages")
@login_required
def messages():
    limit = int(request.args.get("limit", 200))
    return render_template_string(HTML, page="messages", messages=get_messages(limit))


@app.route("/logs")
@login_required
def logs():
    return render_template_string(HTML, page="logs")


@app.route("/api/logs")
@login_required
def api_logs():
    lines = int(request.args.get("lines", 200))
    return jsonify({"lines": get_logs(lines)})


if __name__ == "__main__":
    port = int(os.getenv("ADMIN_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

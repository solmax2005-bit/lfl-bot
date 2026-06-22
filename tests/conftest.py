import pytest

SAMPLE_HTML = """
<html><body>
<h1>Иванов Иван Иванович</h1>
<div class="player-info">
  <span class="position">Нападающий</span>
  <span class="birthdate">15.03.1990</span>
  <a class="club-link" href="/club/42">ФК Алматы</a>
</div>
<table class="stat-table">
  <thead><tr><th>Сезон</th><th>Команда</th><th>М</th><th>Г</th><th>П</th><th>ЖК</th><th>КК</th></tr></thead>
  <tbody>
    <tr><td>2023</td><td>ФК Алматы</td><td>10</td><td>5</td><td>3</td><td>1</td><td>0</td></tr>
    <tr><td>2022</td><td>ФК Тараз</td><td>8</td><td>3</td><td>2</td><td>2</td><td>1</td></tr>
  </tbody>
</table>
</body></html>
"""

SAMPLE_HTML_FREE_AGENT = """
<html><body>
<h1>Петров Пётр Петрович</h1>
<div class="player-info">
  <span class="position">Вратарь</span>
  <span class="birthdate">22.07.1995</span>
  <a class="club-link" href="/club/0">Свободный агент</a>
</div>
<table class="stat-table">
  <thead><tr><th>Сезон</th><th>Команда</th><th>М</th><th>Г</th><th>П</th><th>ЖК</th><th>КК</th></tr></thead>
  <tbody>
    <tr><td>2021</td><td>ФК Звезда</td><td>12</td><td>0</td><td>1</td><td>0</td><td>0</td></tr>
  </tbody>
</table>
</body></html>
"""

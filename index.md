---
title: Головна
layout: default
---

# Нормативна база університету

Перелік положень і наказів, оброблених із `source-pdfs/` у `wiki-pages/`. Згруповано за
таксономією, що відповідає структурі docs.ztu.edu.ua.

{% assign all_docs = site.pages | where_exp: "p", "p.path contains 'wiki-pages/'" %}

{% assign category_order = "Система управління якістю|Загальні організаційні питання|Структурні підрозділи|Формування контингенту студентів. Правила прийому|Освітня діяльність|Наукова, науково-технічна та інноваційна діяльність|Колегіальні органи|Доброчесність та антикорупція|Міжнародна діяльність|Управління персоналом|Інформаційно-бібліотечна та видавнича діяльність|Позанавчальна діяльність. Студентське самоврядування|Фінансово-економічна діяльність|Гуртожитки. Соціальні питання|Охорона праці, безпека життєдіяльності, пожежна безпека|Загальна нормативна база" | split: "|" %}

{% assign faculty_subgroups = "Факультети|Кафедри|Вчена рада факультету|Відділи|Центри|Лабораторії" | split: "|" %}
{% assign collegial_subgroups = "Вчена рада університету|Вибори ректора 2026" | split: "|" %}

{% for category in category_order %}
  {% assign cat_docs = all_docs | where: "category", category | sort: "title" %}
  {% if cat_docs.size > 0 %}
<section class="doc-category">
<h2>{{ category }}</h2>

  {% if category == "Структурні підрозділи" %}
    {% assign general_docs = cat_docs | where_exp: "d", "d.subgroup == nil" %}
    {% include doc-tabs.html groupid="struct" subgroups=faculty_subgroups docs=cat_docs general=general_docs %}

  {% elsif category == "Колегіальні органи" %}
    {% assign general_docs = cat_docs | where_exp: "d", "d.subgroup == nil" %}
    {% include doc-tabs.html groupid="colleg" subgroups=collegial_subgroups docs=cat_docs general=general_docs %}

  {% else %}
<table class="doc-index">
  <thead><tr><th>Документ</th><th>Статус</th><th>№ наказу</th><th>Дата наказу</th></tr></thead>
  <tbody>
    {% for doc in cat_docs %}
    <tr>
      <td><a href="{{ doc.url | relative_url }}">{{ doc.title }}</a></td>
      <td><span class="status">{{ doc.status }}</span></td>
      <td>{{ doc.order_number }}</td>
      <td>{{ doc.order_date }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
  {% endif %}
</section>
  {% endif %}
{% endfor %}

<style>
.doc-index, .doc-meta { border-collapse: collapse; width: 100%; margin: 1em 0; }
.doc-index th, .doc-index td, .doc-meta th, .doc-meta td {
  border: 1px solid #ddd; padding: 6px 10px; text-align: left; vertical-align: top;
}
.doc-meta th { width: 160px; background: #fafafa; }
.status { padding: 2px 8px; border-radius: 4px; font-size: 0.85em; background: #eee; color: #555; }
.doc-category { margin-bottom: 2.5em; }

.doc-tabs { margin-top: 0.5em; }
.doc-tabs .tab-buttons { display: flex; flex-wrap: wrap; background: #eee; border-radius: 6px 6px 0 0; }
.doc-tabs .tab-buttons button {
  background: none; border: none; padding: 0.8em 1.2em; cursor: pointer; font-size: 0.95em;
  border-bottom: 3px solid transparent; color: #333;
}
.doc-tabs .tab-buttons button.active { background: #fff; border-bottom: 3px solid #555; font-weight: 600; }
.doc-tabs .tab-panel { display: none; }
.doc-tabs .tab-panel.active { display: block; }
</style>

<script>
function docTabShow(groupId, idx) {
  var group = document.getElementById(groupId);
  var btns = group.querySelectorAll('.tab-buttons button');
  var panels = group.querySelectorAll('.tab-panel');
  btns.forEach(function(b, i) { b.classList.toggle('active', i === idx); });
  panels.forEach(function(p, i) { p.classList.toggle('active', i === idx); });
}
</script>

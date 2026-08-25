---
title: Головна
layout: default
---

# Нормативна база університету

Пілотний перелік положень і наказів, оброблених RAG-системою з `source-pdfs/` у `wiki-pages/`.

<table class="doc-index">
  <thead>
    <tr>
      <th>Документ</th>
      <th>Статус</th>
      <th>№ наказу</th>
      <th>Дата наказу</th>
    </tr>
  </thead>
  <tbody>
    {% assign docs = site.pages | where_exp: "p", "p.path contains 'wiki-pages/'" | sort: "title" %}
    {% for doc in docs %}
    <tr>
      <td><a href="{{ doc.url | relative_url }}">{{ doc.title }}</a></td>
      <td><span class="status">{{ doc.status }}</span></td>
      <td>{{ doc.order_number }}</td>
      <td>{{ doc.order_date }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<style>
.doc-index, .doc-meta { border-collapse: collapse; width: 100%; margin: 1em 0; }
.doc-index th, .doc-index td, .doc-meta th, .doc-meta td {
  border: 1px solid #ddd; padding: 6px 10px; text-align: left; vertical-align: top;
}
.doc-meta th { width: 160px; background: #fafafa; }
.status { padding: 2px 8px; border-radius: 4px; font-size: 0.85em; background: #eee; color: #555; }
</style>

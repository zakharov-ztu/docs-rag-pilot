// The university's ISO-9001 document form, filled from one wiki-pages .md
// file (sys.inputs.doc): form details come from its frontmatter (`print:`
// block, plus order_number/order_date), the body is parsed here into
// sections / paragraphs / bullets / tables. Used both by
// scripts/render_pdf.py (CLI) and constructor/index.html (in the browser),
// so the form and the .md parsing live only in this file.

#let src = read(sys.inputs.at("doc"))
#let (meta, body) = if src.starts-with("---\n") {
  let end = src.slice(4).position("\n---\n")
  (yaml(bytes(src.slice(4, 4 + end))), src.slice(4 + end + 5))
} else {
  ((:), src)
}
#let meta = if meta == none { (:) } else { meta }
#let pr = meta.at("print", default: none)
#let pr = if pr == none { (:) } else { pr }
#let copy-no = sys.inputs.at("copy", default: "1")
#let controlled = sys.inputs.at("controlled", default: "true") == "true"

// ---- .md body -> blocks ------------------------------------------------------
#let re-heading = regex("^(#{2,6})\\s+(.*\\S)\\s*$")
// Bullet glyphs seen in the corpus, incl. U+F0B7 (Symbol-font bullet that
// Word embeds as a private-use codepoint) and the various dashes.
#let re-bullet = regex("^(?:[\u{f0b7}•●▪]\\s*|[*\\-−–—‒˗]\\s+)")
#let re-link = regex("\\[([^\\]]*)\\]\\([^)]*\\)")
#let re-table-sep = regex("^\\|[\\s:|-]+\\|?$")
// A heading line that is a whole sentence ("### 1. Згідно з Законом ...")
// is a numbered пункт, not a section title, and is printed as a paragraph.
#let section-title-max-chars = 160

#let inline(text) = {
  let t = text.replace(re-link, m => m.captures.at(0))
  t = t.replace("**", "").replace("\\.", ".")
  t.trim()
}

#let parse-blocks(body) = {
  let blocks = ()
  for raw in body.split("\n") {
    let line = raw.trim()
    if line == "" { continue }
    if line.starts-with("|") {
      if line.match(re-table-sep) != none { continue }
      let cells = line.trim("|").split("|").map(inline)
      if blocks.len() > 0 and blocks.last().type == "table" {
        let last = blocks.pop()
        last.rows.push(cells)
        blocks.push(last)
      } else {
        blocks.push((type: "table", rows: (cells,)))
      }
      continue
    }
    let m = line.match(re-heading)
    if m != none {
      let text = inline(m.captures.at(1))
      let is-title = (
        m.captures.at(0).len() <= 3
          and text.clusters().len() <= section-title-max-chars
          and not text.ends-with(".")
          and not text.ends-with(";")
      )
      blocks.push((type: if is-title { "section" } else { "para" }, text: text))
      continue
    }
    let b = line.match(re-bullet)
    if b != none and line.len() > b.end {
      blocks.push((type: "bullet", text: inline(line.slice(b.end))))
      continue
    }
    blocks.push((type: "para", text: inline(line)))
  }
  blocks
}

#let institution = "Державний університет «Житомирська політехніка»"
#let institution-gen = "Державного університету «Житомирська політехніка»"
#let doc-code = pr.at("doc_code", default: "")
#let official-title = pr.at("official_title", default: meta.at("title", default: ""))

#let months = (
  "січня", "лютого", "березня", "квітня", "травня", "червня",
  "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)
#let order-date = {
  let d = meta.at("order_date", default: none)
  if d == none { "" } else { str(d) }
}
#let fmt-date(iso) = {
  if iso.len() < 10 { return iso }
  let (y, m, d) = iso.split("-")
  str(int(d)) + " " + months.at(int(m) - 1) + " " + y + " р."
}
#let year = if order-date.len() >= 4 { order-date.slice(0, 4) } else { "" }

// ---- Page header: the ISO stamp, on every page -------------------------
#let stamp = context {
  let total = counter(page).final().first()
  let current = counter(page).get().first()
  set text(size: 10pt)
  set par(first-line-indent: 0pt, justify: false, leading: 0.35em)
  table(
    columns: (17%, 18%, 16%, 25%, 24%),
    align: center + horizon,
    inset: (x: 3pt, y: 4pt),
    stroke: 0.5pt,
    table.cell(rowspan: 2)[*Житомирська \ політехніка*],
    table.cell(colspan: 3)[*Міністерство освіти і науки України* \ *#institution*],
    doc-code,
    [_Випуск_ #pr.at("issue", default: 1)],
    [_Зміни_ #pr.at("changes", default: 0)],
    [_Екземпляр_ № #copy-no],
    [_Арк_ #total / #current],
  )
}

#set document(title: meta.at("title", default: ""))
#set page(
  paper: "a4",
  margin: (left: 25mm, right: 15mm, top: 36mm, bottom: 20mm),
  header: stamp,
  header-ascent: 6mm,
)
// The in-browser constructor passes font=Tinos, the open, metric-compatible
// Times New Roman clone (TNR itself can't be shipped to the browser).
#set text(font: sys.inputs.at("font", default: "Times New Roman"), size: 14pt, lang: "uk")
#set par(justify: true, leading: 0.55em, spacing: 0.55em, first-line-indent: (amount: 1.25cm, all: true))
#set list(marker: [●], indent: 1.25cm, body-indent: 0.6em)
#show heading: it => {
  set par(first-line-indent: 0pt, justify: false)
  set text(size: 14pt)
  block(above: 1.3em, below: 0.9em, width: 100%, align(center, strong(it.body)))
}

// ---- Cover page ------------------------------------------------------------
#let checkbox(marked) = box(
  width: 1.1em, height: 1.1em, stroke: 0.6pt, baseline: 0.2em,
  align(center + horizon, if marked { [X] }),
)
#{
  set par(first-line-indent: 0pt, justify: false)
  v(0.8cm)
  align(right, block(width: 58%, align(left)[
    *ЗАТВЕРДЖЕНО* \
    Наказ #institution-gen \
    від #fmt-date(order-date) № #meta.at("order_number", default: "") \
    #let ap = pr.at("approver", default: (position: "Ректор", name: ""))
    #ap.position #h(1fr) #ap.name
  ]))
  v(2.2cm)
  align(center, text(weight: "bold", upper(official-title)))
  v(0.8em)
  align(center, strong(doc-code))
  v(1.4cm)
  [#checkbox(controlled) #h(0.5em) Контрольний примірник]
  v(0.6em)
  [#checkbox(not controlled) #h(0.5em) Врахований примірник]
  let council = pr.at("council_approval", default: none)
  if council != none {
    v(1.6cm)
    align(right, block(width: 58%, align(left)[Погоджено \ #council]))
  }
  v(1fr)
  align(center)[Житомир \ #year]
  pagebreak()
}

// ---- Body ---------------------------------------------------------------------
#let render-table(rows) = {
  set text(size: 12pt)
  set par(first-line-indent: 0pt, justify: false)
  let n = calc.max(..rows.map(r => r.len()))
  table(
    columns: n,
    inset: 4pt,
    stroke: 0.5pt,
    ..rows.enumerate().map(((i, r)) => {
      let cells = r + ("",) * (n - r.len())
      cells.map(c => if i == 0 { strong(c) } else { c })
    }).flatten(),
  )
}

#{
  let pending-bullets = ()
  for b in parse-blocks(body) + ((type: "end"),) {
    if b.type != "bullet" and pending-bullets.len() > 0 {
      list(..pending-bullets)
      pending-bullets = ()
    }
    if b.type == "section" { heading(level: 1, b.text) }
    else if b.type == "para" { par(b.text) }
    else if b.type == "bullet" { pending-bullets.push(b.text) }
    else if b.type == "table" { render-table(b.rows) }
  }
}

// ---- Signatures ----------------------------------------------------------------
#let signature-rows(people) = grid(
  columns: (1fr, auto),
  column-gutter: 1cm,
  row-gutter: 1.1em,
  ..people.map(p => (p.position, p.name)).flatten(),
)
#{
  set par(first-line-indent: 0pt, justify: false)
  let developers = pr.at("developers", default: ())
  let agreed = pr.at("agreed", default: ())
  if developers.len() > 0 {
    v(2em)
    signature-rows(developers)
  }
  if agreed.len() > 0 {
    v(1.5em)
    [ПОГОДЖЕНО:]
    v(0.6em)
    signature-rows(agreed)
  }
}

// ---- Standard tracking sheets (blank forms) -------------------------------------
#let form-sheet(code, title, header, widths, rows: 18) = {
  pagebreak()
  set text(size: 12pt)
  set par(first-line-indent: 0pt, justify: false)
  align(right)[(#code)]
  align(center, text(size: 14pt, strong(title)))
  v(0.4em)
  table(
    columns: widths,
    align: center + horizon,
    inset: 4pt,
    stroke: 0.5pt,
    ..header,
    ..range(rows * widths.len()).map(_ => block(height: 0.7cm)),
  )
}

#form-sheet("Ф 03.02-01", "АРКУШ ПОШИРЕННЯ ДОКУМЕНТА",
  ([№ прим.], [Куди передано (підрозділ)], [Дата видачі], [П.І.Б. отримувача], [Підпис отримувача], [Примітки]),
  (9%, 25%, 13%, 22%, 15%, 16%))
#form-sheet("Ф 03.02-02", "АРКУШ ОЗНАЙОМЛЕННЯ З ДОКУМЕНТОМ",
  ([№ пор.], [Прізвище, ім'я, по батькові], [Підпис ознайомленої особи], [Дата ознайомлення], [Примітки]),
  (9%, 35%, 20%, 18%, 18%))
#form-sheet("Ф 03.02-03", "АРКУШ ОБЛІКУ ЗМІН",
  (
    table.cell(rowspan: 2)[№ зміни],
    table.cell(colspan: 4)[№ листа/сторінки (пункту)],
    table.cell(rowspan: 2)[Підпис особи, яка внесла зміну],
    table.cell(rowspan: 2)[Дата внесення зміни],
    table.cell(rowspan: 2)[Дата введення зміни],
    [зміне\u{00AD}ного], [заміне\u{00AD}ного], [нового], [анульо\u{00AD}ваного],
  ),
  (9%, 11%, 11%, 10%, 12%, 17%, 15%, 15%))
#form-sheet("Ф 03.02-04", "АРКУШ РЕЄСТРАЦІЇ РЕВІЗІЙ",
  ([№ пор.], [Прізвище, ім'я, по батькові], [Дата ревізії], [Підпис], [Висновок щодо адекватності]),
  (9%, 33%, 17%, 17%, 24%))

// dependency-free search over search.json + sidebar toggle + TOC highlight
(function () {
  const base = document.body.dataset.base || "/";
  const q = document.getElementById("q"), results = document.getElementById("results");
  let index = null, sel = -1;
  const tok = s => (s || "").toLowerCase().match(/[a-z0-9][a-z0-9_.-]*/g) || [];
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  function score(e, terms) {
    let s = 0; const kw = e.keywords.map(k => k.toLowerCase());
    for (const t of terms) {
      if (kw.some(k => k === t)) s += 5; else if (kw.some(k => k.includes(t))) s += 3;
      if (e.title.toLowerCase().includes(t)) s += 3;
      if (e.slug.includes(t)) s += 2;
      if ((e.description + " " + e.lead).toLowerCase().includes(t)) s += 1;
      if (e.headings.some(h => h.toLowerCase().includes(t))) s += 1;
    }
    return s;
  }
  function render(list) {
    results.innerHTML = list.map(e => `<li><a href="${esc(e.slug === "index" ? base : base + e.slug + "/")}"><div class="r-title">${esc(e.title)}</div><div class="r-meta">${esc(e.group)} · ${esc(e.slug)}</div></a></li>`).join("");
    results.hidden = list.length === 0; sel = -1;
  }
  async function search() {
    const terms = tok(q.value); if (!terms.length) { results.hidden = true; return; }
    if (!index) index = await (await fetch(base + "search.json")).json();
    render(index.map(e => [score(e, terms), e]).filter(x => x[0] > 0).sort((a, b) => b[0] - a[0]).slice(0, 12).map(x => x[1]));
  }
  if (q) {
    q.addEventListener("input", search);
    q.addEventListener("keydown", ev => {
      const items = results.querySelectorAll("li");
      if (ev.key === "ArrowDown") { sel = Math.min(sel + 1, items.length - 1); }
      else if (ev.key === "ArrowUp") { sel = Math.max(sel - 1, 0); }
      else if (ev.key === "Enter" && sel >= 0) { items[sel].querySelector("a").click(); return; }
      else if (ev.key === "Escape") { results.hidden = true; q.blur(); return; }
      else return;
      items.forEach((li, i) => li.classList.toggle("sel", i === sel)); ev.preventDefault();
    });
    document.addEventListener("keydown", ev => { if (ev.key === "/" && document.activeElement !== q) { ev.preventDefault(); q.focus(); } });
    document.addEventListener("click", ev => { if (!ev.target.closest(".search")) results.hidden = true; });
  }
  const toggle = document.querySelector(".nav-toggle");
  if (toggle) toggle.addEventListener("click", () => document.body.classList.toggle("nav-open"));
  const links = [...document.querySelectorAll(".toc a")];
  if (links.length && "IntersectionObserver" in window) {
    const map = new Map(links.map(a => [decodeURIComponent(a.getAttribute("href").slice(1)), a]));
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { links.forEach(l => l.classList.remove("active")); const a = map.get(e.target.id); if (a) a.classList.add("active"); } }), { rootMargin: "-60px 0px -70% 0px" });
    map.forEach((a, id) => { const el = document.getElementById(id); if (el) io.observe(el); });
  }
})();

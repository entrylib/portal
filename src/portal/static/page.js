// The site's one script, on claimset and specification pages. Every part does nothing where its elements are
// absent, and without the script every page still works: the contents link to the sections, a figure's link
// opens the image, and the assistant link opens the reading view.

// Claimset pages: mark the section being read in the contents, and on a phone show it in a bar at the top that opens
// the contents. Without this script the contents still link to every section.
(function () {
  "use strict";
  var nav = document.querySelector(".cs-toc");
  if (!nav || !("IntersectionObserver" in window)) return;
  var links = {};
  nav.querySelectorAll('a[href^="#"]:not(.toc-top)').forEach(function (a) { links[a.getAttribute("href").slice(1)] = a; });
  var sections = Object.keys(links).map(function (id) { return document.getElementById(id); }).filter(Boolean);
  if (!sections.length) return;

  var bar = document.createElement("button");
  bar.type = "button";
  bar.className = "toc-bar";
  bar.setAttribute("aria-expanded", "false");
  bar.setAttribute("aria-controls", "cs-contents");
  nav.id = "cs-contents";
  var label = document.createElement("span");
  bar.appendChild(label);
  nav.parentNode.insertBefore(bar, nav);
  // Shown only on narrow screens; set here too, so that a stale stylesheet never shows it on a wide one.
  var narrow = window.matchMedia("(max-width: 860px)");
  function fit() { bar.hidden = !narrow.matches; if (!narrow.matches) close(); }
  if (narrow.addEventListener) narrow.addEventListener("change", fit);
  function close() { nav.classList.remove("open"); bar.setAttribute("aria-expanded", "false"); }
  bar.addEventListener("click", function () {
    var open = nav.classList.toggle("open");
    bar.setAttribute("aria-expanded", open ? "true" : "false");
  });
  nav.addEventListener("click", function (e) { if (e.target.closest("a")) close(); });

  // The paper view's sections (design §7.4, *Sections*): headings inside Claims, not boxes of their own. Each has an
  // entry in the contents whose title opens the list of its claims and whose arrow (a.pv-toc-go) leads to the
  // heading. The section being read is the last whose heading has passed the line the observer watches; its entry
  // is marked. The lists are the reader's to open and close: nothing here does.
  var parts = [];
  nav.querySelectorAll("a.pv-toc-go").forEach(function (a) {
    var h = document.getElementById(a.getAttribute("href").slice(1));
    if (h) parts.push(h);
  });
  function part(section) {
    var line = window.innerHeight * 0.3 + 1, found = null;
    parts.forEach(function (h) { if (section.contains(h) && h.getBoundingClientRect().top <= line) found = h; });
    return found;
  }
  function entry(a) { return a.closest(".pv-toc-sec"); }
  function set(a, on) {
    if (on) a.setAttribute("aria-current", "location"); else a.removeAttribute("aria-current");
    if (entry(a)) entry(a).classList.toggle("pv-toc-here", on);
  }

  var current = null;
  function mark(id) {
    if (id === current || !links[id]) return;
    if (current && links[current]) set(links[current], false);
    set(links[id], true);
    // Contents taller than the screen scroll on their own: keep the section being read in view in them.
    if (nav.scrollHeight > nav.clientHeight && links[id].offsetParent) {
      var at = links[id].getBoundingClientRect(), box = nav.getBoundingClientRect();
      if (at.top < box.top || at.bottom > box.bottom) nav.scrollTop += at.top - box.top - box.height / 2;
    }
    label.textContent = entry(links[id]) ? entry(links[id]).querySelector("summary").textContent : links[id].textContent;
    current = id;
  }
  var visible = {};
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { visible[e.target.id] = e.isIntersecting; });
    for (var i = 0; i < sections.length; i++) {
      if (visible[sections[i].id]) { mark((part(sections[i]) || sections[i]).id); return; }
    }
  }, { rootMargin: "-15% 0px -70% 0px" });
  sections.forEach(function (s) { observer.observe(s); });
  mark(sections[0].id);
  fit();
  document.documentElement.classList.add("toc-js");
})();

// The site's header: on a phone it slides away while reading down the page and comes back on the first scroll up,
// so the menu is never far; on a wide screen it always stays. Never hidden while its menu is open or near the top.
(function () {
  "use strict";
  var root = document.documentElement, narrow = window.matchMedia("(max-width: 860px)"), last = window.scrollY;
  var menu = document.querySelector(".site-menu");
  window.addEventListener("scroll", function () {
    var y = window.scrollY;
    if (!narrow.matches || y < 120 || (menu && menu.open)) root.classList.remove("head-hidden");
    else if (y > last + 6) root.classList.add("head-hidden");
    else if (y < last - 6) root.classList.remove("head-hidden");
    last = y;
  }, { passive: true });
})();

// Pop-ups: one dialog shape for the whole site, with its close button in the top right corner; Esc, the button or a
// click outside closes it. window.entrylibPopup(className, label) gives {dialog, body, open}.
window.entrylibPopup = function (className, label) {
  "use strict";
  var dialog = document.createElement("dialog");
  dialog.className = "popup " + className;
  dialog.setAttribute("aria-label", label);
  var body = document.createElement("div");
  body.className = "popup-body";
  var close = document.createElement("button");
  close.type = "button";
  close.className = "popup-close";
  close.setAttribute("aria-label", "Close");
  close.textContent = "\u00d7";                         // the multiplication sign, written so it survives any encoding
  dialog.appendChild(body);
  dialog.appendChild(close);
  document.body.appendChild(dialog);
  close.addEventListener("click", function () { dialog.close(); });
  dialog.addEventListener("click", function (e) { if (e.target === dialog) dialog.close(); });
  return { dialog: dialog, body: body, open: function () { dialog.showModal(); close.focus(); } };
};

// Claimset pages: a figure opens enlarged over the page, with its caption. Without this script the figure's link
// opens the image itself.
(function () {
  "use strict";
  if (!window.HTMLDialogElement) return;
  var popup = window.entrylibPopup("zoom", "Figure");
  var figure = document.createElement("figure");
  var img = document.createElement("img");
  var caption = document.createElement("figcaption");
  figure.appendChild(img);
  figure.appendChild(caption);
  popup.body.appendChild(figure);
  popup.dialog.addEventListener("close", function () { img.removeAttribute("src"); });

  // A set of figures (the paper view, design §7.4): the page holds the set once (ol.pv-gallery, each item a
  // figure's address and caption), and a link names the set and where to start (data-gallery, data-i). The pop-up
  // then steps through the set: the buttons, or the arrow keys.
  var nav = document.createElement("div"), count = document.createElement("span");
  var prev = document.createElement("button"), next = document.createElement("button");
  nav.className = "zoom-nav";
  count.className = "zoom-count";
  [[prev, "\u2039", "Previous figure"], [next, "\u203a", "Next figure"]].forEach(function (b) {
    b[0].type = "button";
    b[0].className = "button-quiet";
    b[0].textContent = b[1];
    b[0].setAttribute("aria-label", b[2]);
  });
  nav.appendChild(count);
  nav.appendChild(prev);
  nav.appendChild(next);
  nav.hidden = true;
  popup.body.insertBefore(nav, figure);
  var set = null, at = 0;
  function copy(from) {
    caption.replaceChildren();
    if (from) Array.prototype.forEach.call(from.childNodes, function (n) { caption.appendChild(n.cloneNode(true)); });
  }
  function show(i) {
    at = Math.max(0, Math.min(set.length - 1, i));
    img.src = set[at].getAttribute("data-src");
    img.alt = "";
    copy(set[at]);
    count.textContent = (at + 1) + " of " + set.length;
    prev.disabled = at === 0;
    next.disabled = at === set.length - 1;
  }
  prev.addEventListener("click", function () { show(at - 1); });
  next.addEventListener("click", function () { show(at + 1); });
  popup.dialog.addEventListener("keydown", function (e) {
    if (!set || set.length < 2) return;
    if (e.key === "ArrowLeft") { show(at - 1); e.preventDefault(); }
    if (e.key === "ArrowRight") { show(at + 1); e.preventDefault(); }
  });

  document.addEventListener("click", function (e) {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var member = e.target.closest("a[data-gallery]");
    var list = member && document.getElementById(member.getAttribute("data-gallery"));
    if (list) {
      e.preventDefault();
      set = Array.prototype.slice.call(list.children);
      nav.hidden = set.length < 2;
      show(Number(member.getAttribute("data-i") || 0));
      popup.open();
      return;
    }
    var link = e.target.closest(".cs-figure > a");
    if (!link) return;
    e.preventDefault();
    set = null;
    nav.hidden = true;
    var shown = link.querySelector("img");
    img.src = link.getAttribute("href");
    img.alt = shown ? shown.alt : "";
    copy(link.parentNode.querySelector("figcaption"));
    popup.open();
  });
})();

// The paper view (design §7.4): the rows of a table that bear on a claim open in a pop-up (the page holds them in a
// <template>; without this script the link goes to the claim whose evidence they are), and one button opens every
// proof.
(function () {
  "use strict";
  if (!document.querySelector('.cs-page[data-view="paper"]')) return;
  var rows = window.HTMLDialogElement ? window.entrylibPopup("rows", "Table rows") : null;
  document.addEventListener("click", function (e) {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var link = e.target.closest("a[data-rows]");
    var held = link && document.getElementById(link.getAttribute("data-rows"));
    if (rows && held && held.content) {
      e.preventDefault();
      e.stopPropagation();
      rows.body.replaceChildren(held.content.cloneNode(true));
      rows.open();
      return;
    }
    if (rows && rows.dialog.open && e.target.closest("a[href^='#']")) rows.dialog.close();
  }, true);
  // A link from elsewhere to something only the record holds (/p/<id>#E13, #score): the record shows it.
  var record = document.querySelector('.view-switch a[href$="/record"]');
  function toRecord() {
    var id = decodeURIComponent(location.hash.slice(1));
    if (record && id && !document.getElementById(id)) {
      location.replace(record.getAttribute("href") + "#" + encodeURIComponent(id));
    }
  }
  toRecord();
  window.addEventListener("hashchange", toRecord);
  var all = document.querySelector(".pv-open-all");
  if (all) {
    all.hidden = false;
    all.addEventListener("click", function () {
      var open = all.getAttribute("aria-pressed") !== "true";
      document.querySelectorAll("details.pv-proof").forEach(function (d) { d.open = open; });
      all.setAttribute("aria-pressed", String(open));
      all.textContent = all.getAttribute(open ? "data-close" : "data-open");
    });
  }
  // Printing (the button, or the browser's own command): the page prints whole, with every proof open, and is as
  // it was afterwards. The Record folds and the notices stay shut: they are for checking, not for reading.
  var paper = document.querySelector('.entry[data-view="paper"]');
  if (!paper) return;
  var opened = [];
  function openAll() {
    if (opened.length) return;
    paper.querySelectorAll("details.pv-proof").forEach(function (d) {
      if (!d.open) { d.open = true; opened.push(d); }
    });
    paper.querySelectorAll('img[loading="lazy"]').forEach(function (i) { i.loading = "eager"; });
  }
  window.addEventListener("beforeprint", openAll);
  window.addEventListener("afterprint", function () {
    opened.forEach(function (d) { d.open = false; });
    opened = [];
  });
  var print = document.querySelector(".pv-print");
  if (print && window.print) {
    print.hidden = false;
    var note = document.querySelector(".pv-print-note");
    if (note) note.hidden = false;
    print.addEventListener("click", function () {
      openAll();
      // the figures first: one that has not arrived would print as a gap
      var waits = Array.prototype.map.call(paper.querySelectorAll("img"), function (i) {
        return i.complete ? null : new Promise(function (done) { i.onload = i.onerror = done; });
      });
      var all = Promise.all(waits), late = new Promise(function (done) { setTimeout(done, 4000); });
      Promise.race([all, late]).then(function () { window.print(); });
    });
  }
})();

// Claimset and claim pages: the long sections start folded (design §7.4). Summary, Highlights and the principal claims stay open;
// any other section opens with its title, from the contents, or when the page is opened at something in it. Without
// this script every section is open.
window.entrylibOpen = (function () {
  "use strict";
  // brief: claimset < 0.41.12; claims: the paper view's own section (design §7.4)
  var OPEN = { summary: true, highlights: true, brief: true, principal: true, claims: true };
  var body = document.querySelector(".cs-body");
  function setOpen(section, open) {
    if (!section || !section.classList.contains("fold")) return;
    section.classList.toggle("open", open);
    var b = section.querySelector(".fold-toggle");
    b.setAttribute("aria-expanded", open ? "true" : "false");
    b.querySelector(".fold-state").textContent = open ? "Hide" : "Show";
  }
  function reveal(el) {                       // opens the section that holds `el`, and its folded table
    if (!el) return;
    setOpen(el.closest("section.cs-section.fold"), true);
    var t = el.closest(".cs-table-long");
    if (t && el.classList.contains("cs-more")) foldRows(t, false);
  }
  // Long tables show their first rows and the rows a claim cites; a button shows the rest (design §7.1).
  function foldRows(t, folded) {
    t.classList.toggle("cs-folded", folded);
    var b = t.querySelector(".cs-rows-toggle");
    if (b) {
      b.hidden = false;
      b.textContent = folded ? b.dataset.all : b.dataset.fewer;
      b.setAttribute("aria-expanded", folded ? "false" : "true");
    }
  }
  document.querySelectorAll(".cs-table-long").forEach(function (t) { foldRows(t, true); });
  document.addEventListener("click", function (ev) {        // also in pop-ups, which copy the table
    var b = ev.target.closest && ev.target.closest(".cs-rows-toggle");
    if (b) foldRows(b.closest(".cs-table-long"), !b.closest(".cs-table-long").classList.contains("cs-folded"));
  });
  if (body) {
    body.querySelectorAll(":scope > section.cs-section").forEach(function (s) {
      var h = s.querySelector(":scope > h2");
      if (!h || OPEN[s.id]) return;
      var rest = document.createElement("div");
      rest.className = "fold-body";
      while (h.nextSibling) rest.appendChild(h.nextSibling);
      s.appendChild(rest);
      var count = document.querySelector('.cs-toc a[href="#' + s.id + '"] + .count');
      var b = document.createElement("button");
      b.type = "button";
      b.className = "fold-toggle";
      b.setAttribute("aria-expanded", "false");
      var title = document.createElement("span");
      title.textContent = h.textContent;
      b.appendChild(title);
      if (count) {
        var c = document.createElement("span");
        c.className = "count";
        c.textContent = count.textContent;
        b.appendChild(c);
      }
      var state = document.createElement("span");
      state.className = "fold-state";
      state.textContent = "Show";
      b.appendChild(state);
      h.replaceChildren(b);
      s.classList.add("fold");
      b.addEventListener("click", function () { setOpen(s, !s.classList.contains("open")); });
    });
    document.querySelectorAll('.cs-toc a[href^="#"]').forEach(function (a) {
      a.addEventListener("click", function () { reveal(document.getElementById(a.getAttribute("href").slice(1))); });
    });
    var opened = function () {
      if (location.hash) reveal(document.getElementById(decodeURIComponent(location.hash.slice(1))));
    };
    opened();
    window.addEventListener("hashchange", opened);
  }
  return reveal;
})();

// Claimset and claim pages: a link to an ID (a claim, evidence, a definition or term, an artefact, a reference, a score)
// shows that item in a pop-up instead of moving the page; links inside it show the next item, with a way back.
// Without this script the link goes to the item.
(function () {
  "use strict";
  var body = document.querySelector(".cs-body");
  if (!body || !window.HTMLDialogElement) return;
  var KINDS = { principal: "Principal claim", supporting: "Supporting claim", assumptions: "Assumption",
    definitions: "Definition", evidence: "Evidence", limitations: "Limitation", questions: "Open question",
    references: "Reference", artefacts: "Artefact", context: "Context", score: "Score" };
  var popup = null, head, title, back, content, foot, trail = [];

  function make() {
    popup = window.entrylibPopup("peek", "Item of the claimset");
    popup.body.classList.add("cs-body");                    // the claimset's own styles: tables, formulae
    head = document.createElement("div");
    head.className = "peek-head";
    back = document.createElement("button");
    back.type = "button";
    back.className = "button-quiet";
    back.textContent = "← Back";
    title = document.createElement("p");
    title.className = "peek-title";
    head.appendChild(back);
    head.appendChild(title);
    content = document.createElement("div");
    foot = document.createElement("div");
    foot.className = "peek-foot";
    popup.body.appendChild(head);
    popup.body.appendChild(content);
    popup.body.appendChild(foot);
    back.addEventListener("click", function () { trail.pop(); show(trail[trail.length - 1], true); });
    popup.dialog.addEventListener("close", function () { trail = []; });
  }
  function target(id) {                                    // the item an ID names on this page, and the row in it
    var el = id && document.getElementById(id);
    if (!el || el.tagName === "SECTION" || el.closest("nav") || (popup && popup.dialog.contains(el))) return null;
    var row = el.tagName === "TR" ? el : null;
    if (row) el = row.closest(".cs-item") || row;
    return { el: el, row: row };
  }
  // A score's explanation ("Why 91?", a claim's score): a button that copies the issues it lists, with what the
  // authors' agent is to do with them, as one block to paste. The text is on the page, so the copy happens within the
  // click.
  // An element's text with each formula as its source, $…$ (MathML's text would give the symbols and then the source).
  function plain(el) {
    var copy = el.cloneNode(true);
    copy.querySelectorAll("math").forEach(function (m) {
      var tex = m.querySelector('annotation[encoding="application/x-tex"]');
      m.replaceWith(tex ? "$" + tex.textContent.trim() + "$" : m.textContent);
    });
    return copy.textContent;
  }
  function issuesCopy(el) {
    if (!navigator.clipboard || !/^score-/.test(el.id)) return null;
    var items = el.querySelectorAll(".problems > li");
    if (!items.length) return null;
    var section = el.closest("section") || {};
    var data = section.dataset || {};
    var paper = data.paper || document.title.split(" · ")[0];
    var url = data.url || location.href.split("#")[0];
    var whose = el.id === "score-paper" ? "the paper's score" : "the score of claim " + el.id.slice(6);
    var text = "EntryLib scores " + paper + " (" + url + ") by its public rubric " +
      "(https://github.com/entrylib/rubric/blob/main/RUBRIC.md). The issues below lower " + whose + ", each with " +
      "the points it costs and what would remove it. For each issue, suggest how to fix it: what to change or add " +
      "in the claimset, and where, following the specification and the skills (" + location.origin + "/skills/) " +
      "and the paper, never from memory. If the paper does not have what an issue asks for, say so instead of " +
      "inventing it, and say which issues are not worth fixing, and why. Do not rewrite the claimset yet: give me " +
      "your suggestions, one per issue, and wait for me to decide which to make in a new version of " +
      paper.split("@")[0] + ".\n\n" +
      Array.prototype.map.call(items, function (li) {
        return "- " + plain(li).replace(/\s+/g, " ").trim();
      }).join("\n") + "\n";
    var b = document.createElement("button");
    b.type = "button";
    b.className = "button-quiet";
    var label = "Copy the issues for your agent";
    b.textContent = label;
    b.addEventListener("click", function () {
      navigator.clipboard.writeText(text).then(function () {
        b.textContent = "Copied";
        setTimeout(function () { b.textContent = label; }, 4000);
      });
    });
    return b;
  }
  function show(id, again) {
    var t = target(id);
    if (!t) return false;
    if (!popup) make();
    if (!again) trail.push(id);
    var copy = t.el.cloneNode(true);
    copy.removeAttribute("id");
    copy.querySelectorAll("[id]").forEach(function (n) {
      if (t.row && n.id === t.row.id) n.classList.add("peek-hit");
      n.removeAttribute("id");
    });
    var section = t.el.closest("section.cs-section");
    var name = /^score-/.test(t.el.id) ? t.el.id.slice(6) : t.el.id;
    title.textContent = (name === "paper" ? "The paper" : name) + " · " + ((section && KINDS[section.id]) || "");
    content.replaceChildren(copy);
    back.hidden = trail.length < 2;
    foot.replaceChildren();
    var inPage = document.createElement("button");
    inPage.type = "button";
    inPage.className = "button-quiet";
    inPage.textContent = "Show it in the page";
    inPage.addEventListener("click", function () {
      popup.dialog.close();
      var at = t.row || t.el;
      window.entrylibOpen(at);
      at.scrollIntoView({ block: "center" });
      at.classList.remove("flash");
      void at.offsetWidth;
      at.classList.add("flash");
    });
    foot.appendChild(inPage);
    var issues = issuesCopy(t.el);
    if (issues) foot.appendChild(issues);
    var own = t.el.querySelector("a.claim-page");
    if (own) {
      var a = document.createElement("a");
      a.className = "button-quiet";
      a.href = own.getAttribute("href");
      a.textContent = "Open the claim's own page";
      foot.appendChild(a);
    }
    if (!popup.dialog.open) popup.open();
    popup.body.scrollTop = 0;
    return true;
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest('a[href^="#"]');
    if (!a || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || a.closest(".cs-toc")) return;
    if (!(body.contains(a) || a.closest(".panel") || (popup && popup.dialog.contains(a)))) return;
    var id = a.getAttribute("data-popup") || decodeURIComponent(a.getAttribute("href").slice(1));
    if (show(id)) e.preventDefault();
  });
})();

// Back to the top: the contents start with "↑ Top" (written in the page); this adds a button once the reader is a
// screen down.
(function () {
  "use strict";
  if (!document.querySelector(".cs-body")) return;
  var up = document.createElement("button");
  up.type = "button";
  up.className = "to-top button-quiet";
  up.textContent = "↑ Top";
  up.hidden = true;
  document.body.appendChild(up);
  var smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function top(e) {
    if (e) e.preventDefault();
    window.scrollTo({ top: 0, behavior: smooth ? "smooth" : "auto" });
  }
  up.addEventListener("click", function () { top(); });
  document.querySelectorAll("a.toc-top").forEach(function (a) { a.addEventListener("click", top); });
  window.addEventListener("scroll", function () { up.hidden = window.scrollY < window.innerHeight; }, { passive: true });
})();

// Copy buttons: a button names the element whose text it copies (data-copy) and what to say once it has
// (data-copied). Without the script, or without a clipboard, the button stays hidden and the text is selected by hand.
(function () {
  "use strict";
  if (!navigator.clipboard) return;
  document.querySelectorAll("button[data-copy]").forEach(function (b) {
    var from = document.getElementById(b.getAttribute("data-copy"));
    if (!from) return;
    var label = b.textContent;
    b.hidden = false;
    var note = b.closest(".ask-ai") && b.closest(".ask-ai").querySelector(".ask-copy-note");
    if (note) note.hidden = false;           // what the button does, in the line under the row of buttons
    b.addEventListener("click", function () {
      navigator.clipboard.writeText(from.textContent.trim()).then(function () {
        b.textContent = b.getAttribute("data-copied") || "Copied";
        setTimeout(function () { b.textContent = label; }, 4000);
      }, function () {
        var open = from.closest("details");
        if (open) open.open = true;
      });
    });
  });
})();

// Claimset pages: the note saying what the page is can be closed, and stays closed on this browser. Without the
// script, or without storage, it stays.
(function () {
  var strip = document.getElementById("intro-strip");
  if (!strip) return;
  var key = "entrylib-intro-hidden";
  try {
    if (window.localStorage.getItem(key)) { strip.remove(); return; }
  } catch (e) { return; }
  var close = strip.querySelector(".strip-close");
  if (!close) return;
  close.hidden = false;
  close.addEventListener("click", function () {
    try { window.localStorage.setItem(key, "1"); } catch (e) { /* stays closed for this view only */ }
    strip.remove();
  });
})();

// A help link (data-help="<template id>") opens its template in a pop-up; without the script it goes to its page.
(function () {
  "use strict";
  var popups = {};
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-help]");
    if (!a || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var id = a.getAttribute("data-help"), tpl = document.getElementById(id);
    if (!tpl || !tpl.content) return;
    e.preventDefault();
    if (!popups[id]) {
      popups[id] = window.entrylibPopup("help", a.getAttribute("data-title") || a.textContent);
      popups[id].body.appendChild(tpl.content.cloneNode(true));
    }
    popups[id].open();
  });
})();

// A formula on its own line that is wider than the line (.cs-eq, and a proof step that is a formula alone,
// .cs-step-math): one that is a little too wide is made smaller, so
// that it fits; a wider one keeps its size and scrolls in its box, which the keyboard can then reach. Measured again
// when the box's width changes (a fold opens, the window is resized). Without the script every such formula scrolls.
(function () {
  "use strict";
  var boxes = document.querySelectorAll(".cs-eq, .cs-step-math");
  if (!boxes.length || !("ResizeObserver" in window)) return;
  var SMALLEST = 0.8;                                    // of the formula's own size
  var widths = new WeakMap();
  function fit(box) {
    var math = box.firstElementChild, room = box.clientWidth;
    if (!math || !room || widths.get(box) === room) return;
    widths.set(box, room);
    math.style.fontSize = "";
    var need = box.scrollWidth;
    if (need > room + 1) {
      var scale = Math.floor(100 * room / need) / 100;
      if (scale >= SMALLEST) {
        math.style.fontSize = scale * 100 + "%";
        if (box.scrollWidth > room + 1) math.style.fontSize = (scale - 0.02) * 100 + "%";
      }
    }
    if (box.scrollWidth > room + 1) box.setAttribute("tabindex", "0"); else box.removeAttribute("tabindex");
  }
  var watch = new ResizeObserver(function (entries) { entries.forEach(function (e) { fit(e.target); }); });
  boxes.forEach(function (box) { watch.observe(box); });
  // The maths font may arrive after the first measure, and changes every formula's width.
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () {
    boxes.forEach(function (box) { widths.delete(box); fit(box); });
  });
})();

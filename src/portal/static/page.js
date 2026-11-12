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

  var current = null;
  function mark(id) {
    if (id === current || !links[id]) return;
    if (current && links[current]) links[current].removeAttribute("aria-current");
    links[id].setAttribute("aria-current", "location");
    label.textContent = links[id].textContent;
    current = id;
  }
  var visible = {};
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { visible[e.target.id] = e.isIntersecting; });
    for (var i = 0; i < sections.length; i++) {
      if (visible[sections[i].id]) { mark(sections[i].id); return; }
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

  document.addEventListener("click", function (e) {
    var link = e.target.closest(".cs-figure > a");
    if (!link || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    var shown = link.querySelector("img");
    img.src = link.getAttribute("href");
    img.alt = shown ? shown.alt : "";
    caption.replaceChildren();
    var text = link.parentNode.querySelector("figcaption");
    if (text) Array.prototype.forEach.call(text.childNodes, function (n) { caption.appendChild(n.cloneNode(true)); });
    popup.open();
  });
})();

// Claimset and claim pages: the long sections start folded (design §7.4). In brief and the principal claims stay open;
// any other section opens with its title, from the contents, or when the page is opened at something in it. Without
// this script every section is open.
window.entrylibOpen = (function () {
  "use strict";
  var OPEN = { brief: true, principal: true };
  var body = document.querySelector(".cs-body");
  function setOpen(section, open) {
    if (!section || !section.classList.contains("fold")) return;
    section.classList.toggle("open", open);
    var b = section.querySelector(".fold-toggle");
    b.setAttribute("aria-expanded", open ? "true" : "false");
    b.querySelector(".fold-state").textContent = open ? "Hide" : "Show";
  }
  function reveal(el) {                       // opens the section that holds `el`
    if (el) setOpen(el.closest("section.cs-section.fold"), true);
  }
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
// A link with data-copy-url copies the text at its address (the whole reading view); without the script, or if
// fetching or copying fails, it opens the text instead.
(function () {
  "use strict";
  if (!navigator.clipboard) return;
  document.querySelectorAll("a[data-copy-url]").forEach(function (a) {
    var label = a.textContent;
    a.addEventListener("click", function (e) {
      if (e.ctrlKey || e.metaKey || e.shiftKey) return;
      e.preventDefault();
      var copied = fetch(a.getAttribute("data-copy-url")).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.text();
      });
      var done = function () {
        a.textContent = a.getAttribute("data-copied") || "Copied";
        setTimeout(function () { a.textContent = label; }, 4000);
      };
      var open = function () { window.location.href = a.href; };
      // Safari copies only within the click: hand it the pending text as a ClipboardItem.
      if (window.ClipboardItem && navigator.clipboard.write) {
        navigator.clipboard.write([new ClipboardItem({ "text/plain": copied.then(function (t) {
          return new Blob([t], { type: "text/plain" });
        }) })]).then(done, open);
      } else {
        copied.then(function (t) { return navigator.clipboard.writeText(t); }).then(done, open);
      }
    });
  });
  document.querySelectorAll("button[data-copy]").forEach(function (b) {
    var from = document.getElementById(b.getAttribute("data-copy"));
    if (!from) return;
    var label = b.textContent;
    b.hidden = false;
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
      popups[id] = window.entrylibPopup("help", a.textContent);
      popups[id].body.appendChild(tpl.content.cloneNode(true));
    }
    popups[id].open();
  });
})();

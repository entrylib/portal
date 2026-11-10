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
  nav.querySelectorAll('a[href^="#"]').forEach(function (a) { links[a.getAttribute("href").slice(1)] = a; });
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

// "Copy the link for your AI assistant": copies the reading-view address instead of opening it.
(function () {
  "use strict";
  document.addEventListener("click", function (e) {
    var link = e.target.closest("a.copy-link");
    if (!link || !navigator.clipboard || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    var label = link.textContent;
    navigator.clipboard.writeText(link.href).then(function () {
      link.textContent = "Copied: paste it to your assistant";
      link.classList.add("copied");
      setTimeout(function () { link.textContent = label; link.classList.remove("copied"); }, 4000);
    }, function () { window.location.href = link.href; });
  });
})();

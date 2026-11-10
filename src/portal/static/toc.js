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
  document.documentElement.classList.add("toc-js");
})();

// Claimset pages: a figure opens enlarged over the page, with its caption; Esc, the close button or a click outside
// closes it. Without this script the figure's link opens the image itself.
(function () {
  "use strict";
  if (!window.HTMLDialogElement) return;
  var dialog = document.createElement("dialog");
  dialog.className = "zoom";
  dialog.setAttribute("aria-label", "Figure");
  var figure = document.createElement("figure");
  var img = document.createElement("img");
  var caption = document.createElement("figcaption");
  var close = document.createElement("button");
  close.type = "button";
  close.className = "zoom-close";
  close.setAttribute("aria-label", "Close");
  close.textContent = "×";
  figure.appendChild(img);
  figure.appendChild(caption);
  dialog.appendChild(figure);
  dialog.appendChild(close);
  document.body.appendChild(dialog);

  close.addEventListener("click", function () { dialog.close(); });
  dialog.addEventListener("click", function (e) { if (e.target === dialog) dialog.close(); });
  dialog.addEventListener("close", function () { img.removeAttribute("src"); });

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
    dialog.showModal();
    close.focus();
  });
})();

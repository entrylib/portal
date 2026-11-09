// The upload page (design §4.4): sends the chosen file as the request body of POST /api/submissions and shows the
// answer as text. Nothing from the answer is inserted as HTML.
"use strict";

const MAX_BYTES = 210 * 1024 * 1024;

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function show(nodes) {
  const box = document.getElementById("result");
  box.replaceChildren(...nodes);
}

function problems(title, items) {
  const out = [el("p", title, "error")];
  if (items && items.length) {
    out.push(el("pre", items.map((e) => `rule ${e.rule} at ${e.where || "(file)"}: ${e.message}`).join("\n")));
  }
  return out;
}

document.getElementById("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.getElementById("file").files[0];
  if (!file) return;
  if (file.size > MAX_BYTES) {
    show([el("p", "The file is larger than 210 MB.", "error")]);
    return;
  }
  const button = document.getElementById("send");
  button.disabled = true;
  show([el("p", "Checking…")]);
  const isZip = file.name.toLowerCase().endsWith(".zip");
  const query = document.getElementById("new_paper").checked ? "?new_paper=true" : "";
  try {
    const response = await fetch("/api/submissions" + query, {
      method: "POST",
      body: file,
      headers: { "Content-Type": isZip ? "application/zip" : "application/json" },
    });
    const body = await response.json();
    if (!response.ok) {
      show(problems(body.error || `Refused (${response.status}).`, body.errors));
      return;
    }
    const nodes = [el("p", "Received. It is waiting for the guarantor's consent.")];
    for (const c of body.consent || []) {
      nodes.push(el("p", `Consent link for ${c.name || c.orcid} (shown only now: copy it and give it to them):`));
      const line = el("p");
      const link = el("a", c.consent_url);
      if (/^https?:\/\//.test(c.consent_url)) link.href = c.consent_url;
      line.appendChild(link);
      nodes.push(line);
    }
    nodes.push(el("p", `Submission ${body.id}. Its state: ${body.status_url}`));
    if (body.report && body.report.warnings && body.report.warnings.length) {
      nodes.push(...problems("Warnings (it is valid; you may still want to fix these):", body.report.warnings));
    }
    show(nodes);
  } catch (err) {
    show([el("p", `The submission could not be sent: ${err}`, "error")]);
  } finally {
    button.disabled = false;
  }
});

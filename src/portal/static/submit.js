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

function lines(items) {
  return (items || []).map((e) => `rule ${e.rule} at ${e.where || "(file)"}: ${e.message}`).join("\n");
}

// What the assistant that wrote the file is asked to do with what EntryLib found, with the findings after it: one
// block to paste back to it. The text is on the page already, so the copy happens within the click.
function forAssistant(errors, warnings) {
  const rules = `following the specification and the skills (${location.origin}/skills/) and the paper, never from ` +
    "memory";
  let text;
  if (errors.length) {
    text = `EntryLib refused the claimset you gave me. Fix each error below in the claimset, ${rules}.` +
      (warnings.length ? " Then go through the warnings after them: fix each that applies, and for one that does " +
        "not, tell me why in one line." : "") +
      " Change nothing else, and give me the whole corrected file.\n\nErrors:\n" + lines(errors) + "\n";
  } else {
    text = "EntryLib accepted the claimset you gave me: it is valid, with the warnings below. For each warning, fix " +
      `the claimset if it applies, ${rules}; if it does not apply, tell me why in one line. Change nothing else, ` +
      "and give me the whole corrected file.\n";
  }
  if (warnings.length) text += "\nWarnings:\n" + lines(warnings) + "\n";
  return text;
}

function copyButton(label, text) {
  const row = el("p", undefined, "copy-row");
  if (!navigator.clipboard) return row;               // without a clipboard, the findings above are selected by hand
  const button = el("button", label, "button-quiet");
  button.type = "button";
  button.addEventListener("click", () => navigator.clipboard.writeText(text).then(() => {
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = label; }, 4000);
  }));
  row.appendChild(button);
  return row;
}

function findings(title, items, cls) {
  const out = [el("p", title, cls)];
  if (items.length) out.push(el("pre", lines(items)));
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
      const errors = body.errors || [], warnings = body.warnings || [];
      const nodes = findings(body.error || `Refused (${response.status}).`, errors, "error");
      if (warnings.length) nodes.push(...findings("Warnings, to consider once the errors are fixed:", warnings));
      if (errors.length || warnings.length) {
        nodes.push(copyButton(warnings.length ? "Copy the errors and warnings for your assistant"
          : "Copy the errors for your assistant", forAssistant(errors, warnings)));
        nodes.push(el("p", "Paste it to the assistant that wrote the claimset, then submit the corrected file here.",
          "small"));
      }
      show(nodes);
      // A claimset with the title of one the guarantor already has: offer to submit it as a different paper.
      if (response.status === 409 && /new_paper/.test(body.error || "")) {
        document.getElementById("new_paper_row").hidden = false;
      }
      return;
    }
    const nodes = [el("p", "Received. It is waiting for the responsible researcher's consent.")];
    for (const c of body.consent || []) {
      nodes.push(el("p", `Consent link for ${c.name || c.orcid} (shown only now: copy it and give it to them):`));
      const line = el("p");
      const link = el("a", c.consent_url);
      if (/^https?:\/\//.test(c.consent_url)) link.href = c.consent_url;
      line.appendChild(link);
      nodes.push(line);
    }
    nodes.push(el("p", `Submission ${body.id}. Its state: ${body.status_url}`));
    const warnings = (body.report && body.report.warnings) || [];
    if (warnings.length) {
      nodes.push(...findings("Warnings (it is valid; you may still want to fix these):", warnings));
      nodes.push(copyButton("Copy the warnings for your assistant", forAssistant([], warnings)));
      const next = el("p", "Paste it to the assistant that wrote the claimset. To publish its corrected file " +
        "instead of this one, cancel this submission at ", "small");
      const link = el("a", "Your submissions");
      link.href = "/submissions";
      next.append(link, ", then submit the corrected file here.");
      nodes.push(next);
    }
    show(nodes);
  } catch (err) {
    show([el("p", `The submission could not be sent: ${err}`, "error")]);
  } finally {
    button.disabled = false;
  }
});

"use strict";

const $ = id => document.getElementById(id);
const statusNames = {awaiting_review: "Awaiting review", one_review: "One review", deferred: "Corrections requested",
  disagreement: "Disputed", agreed_approved: "Approved", adjudicated_approved: "Adjudicated", excluded: "Rejected"};
const buckets = {awaiting_review: "pending", one_review: "pending", deferred: "pending",
  disagreement: "disputed", agreed_approved: "approved", adjudicated_approved: "approved", excluded: "rejected"};
const roleNames = {reviewer_a: "Reviewer A", reviewer_b: "Reviewer B", adjudicator: "Adjudicator", coordinator: "Coordinator"};
const decisionNames = {annotate: "Approve with labels", defer: "Request corrections", exclude: "Reject"};
let token = "", dashboard, active;
let requestVersion = 0;

function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function button(text, handler) {
  const el = node("button", text);
  el.type = "button";
  el.addEventListener("click", handler);
  return el;
}
function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}
async function request(path, options = {}) {
  const response = await fetch(path, {...options, headers: {Authorization: "Bearer " + token, ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Check the submitted fields.");
  return data;
}
function field(label, input, parent) {
  const el = node("label", label);
  el.append(input);
  parent.append(el);
  return input;
}
function select(choices, value) {
  const el = node("select");
  for (const [key, text] of choices) {
    const option = node("option", text);
    option.value = key;
    el.append(option);
  }
  el.value = value;
  return el;
}
function renderQueue() {
  const search = $("search").value.trim().toLocaleLowerCase("az");
  const filter = $("filter").value;
  const rows = dashboard.cases.filter(row => (!filter || buckets[row.status] === filter) &&
    [row.id, row.query, row.category].some(value => value.toLocaleLowerCase("az").includes(search)));
  $("queue").replaceChildren(...rows.map(row => {
    const el = button(row.id + " · " + row.query, () => openCase(row.id));
    el.className = "case-button";
    el.setAttribute("aria-current", String(row.id === active));
    el.append(node("span", statusNames[row.status] + (row.control ? " · Control" : "") + (row.submitted ? " · Submitted by you" : "")));
    return el;
  }));
  if (!rows.length) $("queue").append(node("p", "No matching cases."));
}
async function download(kind) {
  try {
    const response = await fetch("/api/export/" + kind, {headers: {Authorization: "Bearer " + token}});
    if (!response.ok) throw new Error("Could not export review records.");
    const url = URL.createObjectURL(await response.blob());
    const link = node("a");
    link.href = url;
    link.download = kind === "bundle" ? "review-bundle.zip" : kind + ".json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { notice(error.message, true); }
}
async function refresh() {
  dashboard = await request("/api/dashboard");
  const counts = dashboard.counts;
  $("identity").textContent = dashboard.reviewer + " · " + roleNames[dashboard.role];
  $("metrics").replaceChildren(...["pending", "approved", "rejected", "disputed"].map(key => {
    const el = node("div", undefined, "metric");
    el.append(node("strong", counts[key]), node("span", key[0].toUpperCase() + key.slice(1)));
    return el;
  }));
  $("completion").max = dashboard.cases.length;
  $("completion").value = counts.approved + counts.rejected;
  $("coverage").textContent = dashboard.cases.length + " cases · " + dashboard.source_checks.verified +
    " source-verified draft records · Legal relevance requires expert review";
  const exports = $("exports");
  exports.className = "actions";
  exports.replaceChildren();
  if (dashboard.role === "coordinator") for (const kind of ["bundle", "progress", "audit"]) {
    exports.append(button("Export " + kind, () => download(kind)));
  }
  renderQueue();
}

function sourceCard(source) {
  const el = node("details", undefined, "source");
  el.open = true;
  el.append(node("summary", [source.document || source.document_id, source.article && "Article " + source.article,
    source.clause && "Clause " + source.clause, source.page && "Page " + source.page].filter(Boolean).join(" · ")));
  el.append(node("p", source.snapshot_verified ? "Verified in frozen corpus" : "Source verification pending", "muted"));
  el.append(node("p", "Document " + source.document_id + " · Passage " + source.passage_id +
    " · Parent " + source.parent_passage_id, "metadata"));
  el.append(node("blockquote", source.text));
  return el;
}

function showDecision(parent, heading, row) {
  const el = node("details", undefined, "review");
  const value = row.decision;
  el.append(node("summary", heading + " · " + decisionNames[value.decision]),
    node("p", value.reason), node("p", row.saved_at + " · Revision " + (row.revision || row.id), "muted"));
  if (value.labels) el.append(node("pre", JSON.stringify(value.labels, null, 2)));
  parent.append(el);
}

function renderCase(id, data) {
  const detail = $("detail"), item = data.case;
  detail.replaceChildren(node("p", id + " · " + item.category + " · " + statusNames[data.status], "metadata"),
    node("h2", item.query));
  for (const entry of item.history) detail.append(node("p", typeof entry === "string" ? entry : JSON.stringify(entry), "muted"));
  if (item.standalone) detail.append(node("p", "Draft standalone wording: " + item.standalone, "muted"));
  if (data.disputed_fields.length) detail.append(node("p", "Disputed fields: " + data.disputed_fields.join(", "), "dispute"));
  for (const [role, row] of Object.entries(data.peers)) showDecision(detail, roleNames[role], row);
  if (data.history.length) {
    const history = node("details");
    history.append(node("summary", "Revision history (" + data.history.length + ")"));
    for (const row of data.history) showDecision(history, roleNames[row.role], row);
    detail.append(history);
  }
  if (!data.editable) {
    detail.append(node("h3", "Candidate legal sources"));
    if (!item.draft_evidence.length) detail.append(node("p", "No candidate evidence in the packet.", "muted"));
    for (const source of item.draft_evidence) detail.append(sourceCard(source));
    return;
  }
  renderForm(detail, id, data);
}

function renderForm(detail, id, data) {
  const item = data.case, saved = data.own?.decision, labels = saved?.labels;
  const form = node("form");
  const decision = field("Review decision", select([["", "Select a decision"], ...Object.entries(decisionNames)],
    saved?.decision || ""), form);
  decision.required = true;
  const reason = field("Rationale", node("textarea"), form);
  reason.required = true;
  reason.maxLength = 8000;
  reason.value = saved?.reason || "";
  const settings = node("fieldset");
  settings.append(node("legend", "Legal annotation"));
  const answerability = field("Answerability", select([["", "Select answerability"], ["answerable", "Answerable"],
    ["partially_answerable", "Partially answerable"], ["unanswerable", "Unanswerable"], ["ambiguous", "Ambiguous"],
    ["conflicting", "Conflicting"]], labels?.answerability || ""), settings);
  const answer = field("Expected answer or response", node("textarea"), settings);
  answer.value = labels?.expected_answer || "";
  const standalone = field("Standalone query, if needed", node("input"), settings);
  standalone.value = labels?.standalone || "";
  const qualifications = field("Required qualifications, one per line", node("textarea"), settings);
  qualifications.value = (labels?.required_qualifications || []).join("\n");
  const groups = field("Evaluation groups, comma separated", node("input"), settings);
  groups.value = (labels?.groups || item.groups).join(", ");

  const parts = new Map();
  const partsView = node("fieldset");
  partsView.append(node("legend", "Multipart associations"));
  function addPart(partId, question = "", suggested = []) {
    const input = field(partId + " question", node("input"), partsView);
    input.value = question;
    if (suggested.length) partsView.append(node("p", "Draft passage IDs: " + suggested.join(", "), "metadata"));
    parts.set(partId, input);
  }
  for (const partId of new Set([...Object.keys(item.draft_part_parents), ...Object.keys(labels?.parts || {})])) {
    addPart(partId, labels?.parts[partId]?.question, item.draft_part_parents[partId]);
  }
  const partButton = button("Add sub-question", () => {
    let i = 1;
    while (parts.has("Q" + i)) i++;
    addPart("Q" + i);
    for (const entry of entries.values()) addPartOption(entry, "Q" + i, false);
  });
  settings.append(partsView, partButton);
  form.append(settings, node("h3", "Candidate legal sources"));
  const sources = node("div");
  const entries = new Map();
  function addPartOption(entry, partId, selected) {
    const check = node("input");
    check.type = "checkbox";
    check.checked = selected;
    entry.parts.set(partId, check);
    field(partId, check, entry.config);
  }
  function addSource(source) {
    if (entries.has(source.passage_id)) return;
    const savedSource = labels?.evidence.find(value => value.passage_id === source.passage_id);
    const config = node("div", undefined, "source-settings");
    const grade = select([["", "Unselected"], ["1", "1 · Context"], ["2", "2 · Supporting"], ["3", "3 · Controlling"]],
      savedSource ? String(savedSource.relevance) : "");
    const required = node("input");
    required.type = "checkbox";
    required.checked = labels?.required_passage_ids.includes(source.passage_id) || false;
    field("Relevance", grade, config);
    field("Required passage", required, config);
    const entry = {source, grade, required, config, parts: new Map()};
    for (const partId of parts.keys()) addPartOption(entry, partId, labels?.parts[partId]?.required_passage_ids.includes(source.passage_id));
    const card = sourceCard(source);
    card.append(config);
    sources.append(card);
    entries.set(source.passage_id, entry);
  }
  for (const source of [...item.draft_evidence, ...(labels?.evidence || [])]) addSource(source);
  if (!entries.size) sources.append(node("p", "No candidate evidence in the packet.", "muted"));
  const lookup = node("div");
  const pid = field("Add passage by frozen corpus ID", node("input"), lookup);
  lookup.append(button("Load passage", async () => {
    try { addSource(await request("/api/passages/" + encodeURIComponent(pid.value.trim()))); pid.value = ""; }
    catch (error) { notice(error.message, true); }
  }));
  const save = node("button", "Submit revision", "primary");
  form.append(sources, lookup, save);
  detail.append(form);
  const update = () => { settings.hidden = decision.value !== "annotate";
    for (const entry of entries.values()) entry.config.hidden = settings.hidden; };
  decision.onchange = update;
  update();
  form.onsubmit = async event => {
    event.preventDefault();
    const body = {decision: decision.value, reason: reason.value, previous: data.own?.revision || 0, labels: null,
      reviewed_decision_sha256: data.decision_hashes};
    if (decision.value === "annotate") {
      const selected = [...entries.values()].filter(entry => entry.grade.value);
      if ([...entries.values()].some(entry => !entry.grade.value &&
          (entry.required.checked || [...entry.parts.values()].some(check => check.checked)))) {
        notice("Choose a relevance grade for each required or assigned passage.", true);
        return;
      }
      body.labels = {answerability: answerability.value, expected_answer: answer.value.trim(), standalone: standalone.value.trim() || null,
        required_qualifications: qualifications.value.split("\n").map(x => x.trim()).filter(Boolean),
        groups: [...new Set(groups.value.split(",").map(x => x.trim()).filter(Boolean))],
        evidence: selected.map(entry => {
          const {passage_id, parent_passage_id, document_id, article, clause, text} = entry.source;
          return {passage_id, parent_passage_id, document_id, article: article ?? null, clause: clause ?? null, text,
            relevance: Number(entry.grade.value)};
        }),
        required_passage_ids: selected.filter(entry => entry.required.checked).map(entry => entry.source.passage_id),
        parts: Object.fromEntries([...parts].map(([key, input]) => [key, {question: input.value.trim(),
          required_passage_ids: selected.filter(entry => entry.parts.get(key)?.checked).map(entry => entry.source.passage_id)}]))};
    }
    save.disabled = true;
    try {
      await request("/api/cases/" + encodeURIComponent(id), {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      await refresh();
      if (active === id) await openCase(id);
      notice("Revision submitted.");
    } catch (error) { notice(error.message, true); }
    finally { save.disabled = false; }
  };
}

async function openCase(id) {
  const version = ++requestVersion;
  active = id;
  renderQueue();
  try {
    const data = await request("/api/cases/" + encodeURIComponent(id));
    if (version === requestVersion && token) renderCase(id, data);
  } catch (error) { if (version === requestVersion) notice(error.message, true); }
}
$("login").addEventListener("submit", async event => {
  event.preventDefault();
  token = $("token").value.trim();
  $("token").value = "";
  try {
    await refresh();
    $("login").hidden = true;
    $("sign-out").hidden = false;
    $("workspace").hidden = false;
    notice("");
  } catch (error) { token = ""; notice(error.message, true); }
});
$("sign-out").addEventListener("click", () => location.reload());
$("search").addEventListener("input", renderQueue);
$("filter").addEventListener("change", renderQueue);

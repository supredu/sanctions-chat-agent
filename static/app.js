const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message");
const sessionPill = document.querySelector("#session-pill");
const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";

let sessionId = readSessionId();

function readSessionId() {
  try {
    return window.localStorage.getItem("sanctions_chat_session_id");
  } catch {
    return null;
  }
}

function saveSessionId(value) {
  try {
    window.localStorage.setItem("sanctions_chat_session_id", value);
  } catch {
    // The chat can still work without browser storage.
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderAnswerText(value) {
  return escapeHtml(value)
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^字段[：:]\s*/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^---+$/gm, "")
    .replace(/\n/g, "<br>");
}

function appendMessage(role, html) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.innerHTML = html;
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
  return article;
}

function field(label, value) {
  return `
    <div>
      <dt>${escapeHtml(label)}</dt>
      <dd>${escapeHtml(value || "-")}</dd>
    </div>
  `;
}

function renderResultCard(result) {
  if (!result) {
    return "";
  }

  const finding = result.finding || {};
  const evidence = result.evidence || [];
  const relatedHits = result.related_hits || [];

  return `
    <section class="result-card">
      <div class="card-head">
        <h2>${finding.direct_sanction_hit ? "Direct Sanctions Hit" : finding.related_sanction_hit ? "Related Sanctions Hit" : "No Local Hit"}</h2>
        <span class="status ${finding.direct_sanction_hit ? "danger" : finding.related_sanction_hit ? "warn" : "neutral"}">${escapeHtml(result.confidence || "unknown")}</span>
      </div>
      <dl class="fields">
        ${field("Query type", result.query_type)}
        ${field("Sanctioned object", finding.sanctioned_entity)}
        ${field("Authority", finding.sanction_authority)}
        ${field("Sanction date", finding.sanction_date)}
        ${field("Program", finding.program)}
        ${field("Reason", finding.sanction_reason)}
      </dl>
      <p class="summary">${escapeHtml(result.summary || "")}</p>
      ${renderEvidence(evidence)}
      ${renderRelatedHits(relatedHits)}
      ${renderGaps(result.gaps || [])}
    </section>
  `;
}

function renderEvidence(evidence) {
  if (!evidence.length) {
    return "";
  }

  const items = evidence.slice(0, 6).map((item) => {
    const title = escapeHtml(item.source_title || "Source");
    const publisher = escapeHtml(item.publisher || "Unknown publisher");
    const date = escapeHtml(item.publication_date || "No publication date");
    const url = item.source_url
      ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.source_url)}</a>`
      : "<span>No URL</span>";
    return `<li><strong>${title}</strong><span>${publisher} | ${date}</span>${url}</li>`;
  });

  return `
    <div class="evidence">
      <h3>Evidence</h3>
      <ul>${items.join("")}</ul>
    </div>
  `;
}

function renderRelatedHits(relatedHits) {
  if (!relatedHits.length) {
    return "";
  }

  const items = relatedHits.slice(0, 5).map((hit) => {
    return `<li>${escapeHtml(hit.description)} ${escapeHtml(hit.sanctioned_entity || "")}</li>`;
  });

  return `
    <div class="evidence">
      <h3>Related hits</h3>
      <ul>${items.join("")}</ul>
    </div>
  `;
}

function renderGaps(gaps) {
  if (!gaps.length) {
    return "";
  }

  return `<p class="gaps">${escapeHtml(gaps.join(" "))}</p>`;
}

function renderCandidates(candidates) {
  if (!candidates.length) {
    return "";
  }

  const buttons = candidates.map((candidate, index) => {
    const name = candidate.name || candidate.entity_name || "Unknown entity";
    const authority = candidate.authority || "Unknown authority";
    const dates = candidate.sanction_dates || [];
    return `
      <button class="candidate" type="button" data-choice="${index + 1}">
        <strong>${escapeHtml(index + 1)}. ${name}</strong>
        <span>${escapeHtml(authority)} | ${escapeHtml(dates[0] || "No official date")}</span>
      </button>
    `;
  });

  return `<div class="candidates">${buttons.join("")}<button class="candidate muted" type="button" data-choice="none"><strong>以上没有命中</strong><span>改为联网查询这个实体名称</span></button></div>`;
}

function renderActions(actions) {
  if (!actions.length) {
    return "";
  }

  const items = actions.map((action) => {
    const suffix = action.suggested_query || action.explorer_url || "";
    return `<li><strong>${escapeHtml(action.type)}</strong>: ${escapeHtml(action.description)}<span>${escapeHtml(suffix)}</span></li>`;
  });

  return `
    <details class="actions" open>
      <summary>Reserved next actions</summary>
      <ul>${items.join("")}</ul>
    </details>
  `;
}

function renderWebEnrichment(enrichment) {
  if (!enrichment) {
    return "";
  }

  const sources = enrichment.sources || [];
  const pages = enrichment.page_evidence || [];
  const sourceItems = sources.slice(0, 6).map((source) => {
    return `
      <li>
        <strong>${escapeHtml(source.title || source.publisher || "Web source")}</strong>
        <a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.url)}</a>
        <span>${escapeHtml(source.snippet || source.source_type || "")}</span>
      </li>
    `;
  });
  const pageItems = pages.slice(0, 3).map((page) => {
    const markers = page.matched_markers?.length ? page.matched_markers.join(", ") : "No sanction markers";
    const title = escapeHtml(page.title || page.url);
    const url = escapeHtml(page.url);
    return `
      <li>
        <strong><a href="${url}" target="_blank" rel="noreferrer">${title}</a></strong>
        <span>${escapeHtml(page.description || page.error || "")}</span>
        <span>${escapeHtml(markers)}</span>
      </li>
    `;
  });

  return `
    <section class="web-card">
      <h3>Web enrichment</h3>
      <p>${escapeHtml(enrichment.summary || "")}</p>
      ${sourceItems.length ? `<ul>${sourceItems.join("")}</ul>` : "<p>No public web results returned.</p>"}
      ${pageItems.length ? `<h3>已读取的网页证据</h3><ul>${pageItems.join("")}</ul>` : ""}
    </section>
  `;
}

function renderExplorerContext(context) {
  if (!context) {
    return "";
  }

  const evidence = context.evidence || {};
  const markers = evidence.matched_markers?.length ? evidence.matched_markers.join(", ") : "No sanction markers";
  const url = context.url
    ? `<a href="${escapeHtml(context.url)}" target="_blank" rel="noreferrer">${escapeHtml(context.url)}</a>`
    : "<span>No explorer URL</span>";

  return `
    <section class="web-card">
      <h3>Explorer check</h3>
      <p>${escapeHtml(context.summary || "")}</p>
      ${url}
      <span>${escapeHtml(markers)}</span>
    </section>
  `;
}

function renderLlmResearch(research) {
  if (!research) {
    return "";
  }
  const status = research.error ? `${research.status}: ${research.error}` : research.status;
  const calls = research.web_search_calls?.length || 0;
  return `
    <details class="actions">
      <summary>LLM research</summary>
      <ul>
        <li><strong>${escapeHtml(research.provider || "llm")}</strong><span>${escapeHtml(status)}</span><span>web search calls: ${escapeHtml(calls)}</span></li>
      </ul>
    </details>
  `;
}

async function sendMessage(message) {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: sessionId,
      message,
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Chat request failed");
  }
  sessionId = payload.session_id;
  saveSessionId(sessionId);
  sessionPill.textContent = `Session ${sessionId.slice(0, 8)}`;
  return payload;
}

function renderAssistant(payload) {
  const html = `
    <p>${renderAnswerText(payload.answer)}</p>
    ${renderCandidates(payload.candidates || [])}
    ${renderResultCard(payload.result)}
    ${renderWebEnrichment(payload.web_enrichment)}
    ${renderExplorerContext(payload.explorer_context)}
    ${renderLlmResearch(payload.llm_research)}
    ${renderActions(payload.next_actions || [])}
  `;
  appendMessage("assistant", html);
}

async function handleUserMessage(message) {
  appendMessage("user", `<p>${escapeHtml(message)}</p>`);
  input.value = "";
  input.style.height = "auto";

  const loading = appendMessage("assistant", `<p>正在查询...</p>`);
  try {
    const payload = await sendMessage(message);
    loading.remove();
    renderAssistant(payload);
  } catch (error) {
    loading.innerHTML = `<p>${escapeHtml(error.message || String(error))}</p>`;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) {
    input.focus();
    return;
  }
  await handleUserMessage(message);
});

messages.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-choice]");
  if (!button) {
    return;
  }
  const choice = button.dataset.choice === "none" ? "以上没有命中" : button.dataset.choice;
  await handleUserMessage(choice);
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
});

input.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey) {
    return;
  }
  event.preventDefault();
  form.requestSubmit();
});

try {
  appendMessage(
    "assistant",
    `<p>请输入区块链地址或实体名称。支持实体名称模糊查询；如果本地库匹配到多个实体，我会先让你选择，再继续联网核查。</p>`
  );
} catch (error) {
  document.body.insertAdjacentHTML(
    "beforeend",
    `<pre style="color:#b91c1c;padding:16px;">前端初始化失败：${escapeHtml(error.message || String(error))}</pre>`
  );
}

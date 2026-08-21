const DATA_URL = document.body.dataset.resultsUrl || "./data/comparison.json";
const ANSWERS_URL = document.body.dataset.answersUrl || "./data/answers/manifest.json";
const LATENCY_URL = document.body.dataset.latencyUrl || "./data/latency.json";

const MODEL_COLORS = ["#c8ff61", "#6ee7b7", "#66d8e5", "#ffcb66"];
const CATEGORY_COPY = {
  simple: {
    label: "Simple",
    title: "Simple tool calls",
    description: "One function, one precise set of arguments.",
  },
  multiple: {
    label: "Multiple",
    title: "Multiple choices",
    description: "Choose the correct function from several available tools.",
  },
  irrelevance: {
    label: "Irrelevance",
    title: "Tool restraint",
    description: "Recognize when no available function should be called.",
  },
  chatable: {
    label: "Chatable",
    title: "Conversation",
    description: "Reply naturally when the prompt needs text, not a tool call.",
  },
};

const percent = (value) => `${(value * 100).toFixed(2)}%`;
const wholePercent = (value) => `${(value * 100).toFixed(2).replace(/\.00$/, "")}%`;
let categoryAnimationFrame;
const ANSWERS_PER_PAGE = 8;
const ANSWER_FETCH_TIMEOUT_MS = 15_000;
const answerState = {
  manifest: null,
  cases: [],
  page: 1,
  result: "all",
  search: "",
};
const answerCategoryCache = new Map();
const answerSearchText = new WeakMap();
let answerLoadSequence = 0;
let answerSearchTimer;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function modelLabel(result) {
  const label = element("div", "model-label");
  label.append(element("strong", "", result.model));
  label.append(element("span", "", `Rank ${result.rank}`));
  return label;
}

function barTrack(value, color, label) {
  const track = element("div", "bar-track");
  const fill = element("div", "bar-fill");
  fill.style.setProperty("--bar-color", color);
  fill.setAttribute("role", "img");
  fill.setAttribute("aria-label", label);
  fill.dataset.width = `${value * 100}%`;
  track.append(fill);
  return track;
}

function animateBars(container) {
  container.querySelectorAll(".bar-fill").forEach((fill) => {
    fill.style.width = fill.dataset.width;
  });
}

function renderOverall(results) {
  const chart = document.querySelector("#overall-chart");
  chart.replaceChildren();

  results.forEach((result, index) => {
    const row = element("div", "leaderboard-row");
    row.append(modelLabel(result));
    row.append(
      barTrack(
        result.accuracy,
        MODEL_COLORS[index % MODEL_COLORS.length],
        `${result.model}: ${percent(result.accuracy)} overall accuracy`,
      ),
    );
    row.append(element("div", "bar-value", percent(result.accuracy)));
    chart.append(row);
  });
  requestAnimationFrame(() => animateBars(chart));
}

function renderCategory(results, colorIndexByModelId, category) {
  const copy = CATEGORY_COPY[category];
  document.querySelector("#category-label").textContent = copy.label;
  document.querySelector("#category-title").textContent = copy.title;
  document.querySelector("#category-description").textContent = copy.description;

  document.querySelectorAll(".category-button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.category === category));
  });

  const chart = document.querySelector("#category-chart");
  chart.replaceChildren();
  const categoryResults = [...results].sort(
    (first, second) => second.by_category[category].accuracy - first.by_category[category].accuracy,
  );

  categoryResults.forEach((result) => {
    const detail = result.by_category[category];
    const colorIndex = colorIndexByModelId.get(result.model_id);
    const row = element("div", "category-row");
    row.append(modelLabel(result));
    row.append(
      barTrack(
        detail.accuracy,
        MODEL_COLORS[colorIndex % MODEL_COLORS.length],
        `${result.model}: ${percent(detail.accuracy)} in ${copy.label}`,
      ),
    );
    const score = element("div", "category-detail");
    score.append(element("strong", "", wholePercent(detail.accuracy)));
    score.append(element("span", "", `${detail.passed} / ${detail.scored}`));
    row.append(score);
    chart.append(row);
  });
  cancelAnimationFrame(categoryAnimationFrame);
  categoryAnimationFrame = requestAnimationFrame(() => animateBars(chart));
}

function renderControls(results, colorIndexByModelId, categories, selectedCategory) {
  const controls = document.querySelector("#category-controls");
  controls.replaceChildren();
  categories.forEach((category, index) => {
    const button = element("button", "category-button", CATEGORY_COPY[category]?.label ?? category);
    button.type = "button";
    button.dataset.category = category;
    button.setAttribute("aria-pressed", String(category === selectedCategory));
    button.addEventListener("click", () => {
      const url = new URL(window.location);
      url.searchParams.set("category", category);
      window.history.replaceState({}, "", url);
      renderCategory(results, colorIndexByModelId, category);
    });
    controls.append(button);
  });
}

function scoreCell(detail) {
  return element("td", "", `${detail.passed}/${detail.scored} · ${wholePercent(detail.accuracy)}`);
}

function renderTable(results) {
  const body = document.querySelector("#results-table-body");
  body.replaceChildren();

  results.forEach((result) => {
    const row = document.createElement("tr");
    const rank = document.createElement("td");
    rank.append(element("span", "rank-badge", String(result.rank)));
    row.append(rank);
    row.append(element("td", "", result.model));
    row.append(element("td", "", `${result.passed}/${result.scored} · ${wholePercent(result.accuracy)}`));
    row.append(scoreCell(result.by_category.simple));
    row.append(scoreCell(result.by_category.multiple));
    row.append(scoreCell(result.by_category.irrelevance));
    row.append(scoreCell(result.by_category.chatable));
    body.append(row);
  });
}

function renderSummary(data) {
  const [leader, runnerUp] = data.results;
  const multipleLeader = [...data.results].sort(
    (first, second) => second.by_category.multiple.accuracy - first.by_category.multiple.accuracy,
  )[0];
  const margin = (leader.accuracy - runnerUp.accuracy) * 100;
  document.querySelector("#leading-score").textContent = percent(leader.accuracy);
  document.querySelector("#leading-model").textContent = leader.model;
  document.querySelector("#lead-margin").textContent = `${margin.toFixed(2)} points ahead of ${runnerUp.model}`;
  document.querySelector("#leader-insight").textContent =
    `${leader.model} leads overall by ${margin.toFixed(2)} points, while ${multipleLeader.model} wins the multiple-tool category.`;
  document.querySelector("#case-count").textContent = data.total_cases.toLocaleString("en-US");
  document.querySelector("#model-count").textContent = String(data.results.length);
  document.querySelector("#category-count").textContent = String(data.categories.length);
  document.querySelector("#dataset-revision").textContent = `Pinned at ${data.dataset_revision.slice(0, 10)}`;
}

function questionText(question) {
  if (typeof question === "string") return question;
  if (Array.isArray(question)) return question.map(questionText).filter(Boolean).join("\n");
  if (question && typeof question === "object") {
    if (typeof question.content === "string") return question.content;
    return JSON.stringify(question, null, 2);
  }
  return "";
}

function jsonBlock(value, emptyMessage) {
  const pre = element("pre", "answer-json");
  const isEmpty = value == null || value === "" || (Array.isArray(value) && value.length === 0);
  pre.textContent = isEmpty ? emptyMessage : JSON.stringify(value, null, 2);
  return pre;
}

function safeMarkdownLink(rawHref) {
  try {
    const url = new URL(rawHref, window.location.href);
    return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function appendInlineMarkdown(parent, text) {
  const tokenPattern = /(?:\\\*|`[^`\n]+`|\*\*[^*\n]+?\*\*|__[^_\n]+?__|(?<![\\*])\*(?![\s*])(?:\\.|[^*\\\n])*(?<![\s\\])\*(?!\*)|\[[^\]\n]+\]\([^\s)]+\))/g;
  let cursor = 0;

  for (const match of text.matchAll(tokenPattern)) {
    const token = match[0];
    const offset = match.index;
    parent.append(text.slice(cursor, offset));
    if (token === "\\*") {
      parent.append("*");
    } else if (token.startsWith("`")) {
      parent.append(element("code", "", token.slice(1, -1)));
    } else if (token.startsWith("**") || token.startsWith("__")) {
      parent.append(element("strong", "", token.slice(2, -2)));
    } else if (token.startsWith("*")) {
      parent.append(element("em", "", token.slice(1, -1)));
    } else {
      const separator = token.lastIndexOf("](");
      const label = token.slice(1, separator);
      const href = safeMarkdownLink(token.slice(separator + 2, -1));
      if (href) {
        const link = element("a", "", label);
        link.href = href;
        link.rel = "noopener noreferrer";
        parent.append(link);
      } else {
        parent.append(token);
      }
    }
    cursor = offset + token.length;
  }
  parent.append(text.slice(cursor));
}

function markdownTableCells(line) {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => cell.trim());
}

function isMarkdownTableDivider(line) {
  return markdownTableCells(line).every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isMarkdownBlockStart(lines, index) {
  const line = lines[index];
  return (
    /^\s*```/.test(line)
    || /^#{1,6}\s+/.test(line)
    || /^\s*(?:[-+*]|\d+[.)])\s+/.test(line)
    || /^>\s?/.test(line)
    || /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)
    || (line.includes("|") && index + 1 < lines.length && isMarkdownTableDivider(lines[index + 1]))
  );
}

function appendMarkdownLines(parent, lines) {
  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^\s*```([^\s`]*)\s*$/);
    if (fence) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const code = element("code", fence[1] ? `language-${fence[1]}` : "", codeLines.join("\n"));
      const pre = element("pre", "markdown-code-block");
      pre.append(code);
      parent.append(pre);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const headingNode = element("h5", `markdown-heading markdown-heading-${heading[1].length}`);
      appendInlineMarkdown(headingNode, heading[2]);
      parent.append(headingNode);
      index += 1;
      continue;
    }

    if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      parent.append(element("hr"));
      index += 1;
      continue;
    }

    if (line.includes("|") && index + 1 < lines.length && isMarkdownTableDivider(lines[index + 1])) {
      const table = element("table", "markdown-table");
      const head = element("thead");
      const headRow = element("tr");
      markdownTableCells(line).forEach((cell) => {
        const header = element("th");
        appendInlineMarkdown(header, cell);
        headRow.append(header);
      });
      head.append(headRow);
      table.append(head);
      index += 2;
      const body = element("tbody");
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        const row = element("tr");
        markdownTableCells(lines[index]).forEach((cell) => {
          const data = element("td");
          appendInlineMarkdown(data, cell);
          row.append(data);
        });
        body.append(row);
        index += 1;
      }
      table.append(body);
      const tableWrap = element("div", "markdown-table-wrap");
      tableWrap.append(table);
      parent.append(tableWrap);
      continue;
    }

    const listItem = line.match(/^\s*([-+*]|\d+[.)])\s+(.+)$/);
    if (listItem) {
      const ordered = /^\d/.test(listItem[1]);
      const list = element(ordered ? "ol" : "ul");
      if (ordered) {
        const start = Number.parseInt(listItem[1], 10);
        if (start !== 1) list.start = start;
      }
      while (index < lines.length) {
        const item = lines[index].match(/^\s*([-+*]|\d+[.)])\s+(.+)$/);
        if (!item || /^\d/.test(item[1]) !== ordered) break;
        const listNode = element("li");
        appendInlineMarkdown(listNode, item[2]);
        list.append(listNode);
        index += 1;
      }
      parent.append(list);
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quoteLines = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      const quote = element("blockquote");
      appendMarkdownLines(quote, quoteLines);
      parent.append(quote);
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !isMarkdownBlockStart(lines, index)) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    const paragraph = element("p");
    paragraphLines.forEach((paragraphLine, lineIndex) => {
      if (lineIndex) paragraph.append(element("br"));
      appendInlineMarkdown(paragraph, paragraphLine);
    });
    parent.append(paragraph);
  }
}

function renderMarkdown(markdown) {
  const fragment = document.createDocumentFragment();
  appendMarkdownLines(fragment, markdown.replace(/\r\n?/g, "\n").split("\n"));
  return fragment;
}

function renderAnswerCard(answer, modelById) {
  const card = element("article", "model-answer");
  const header = element("div", "model-answer-header");
  header.append(element("h4", "", modelById.get(answer.model_id) || answer.model_id));
  header.append(
    element(
      "span",
      `answer-status ${answer.passed ? "answer-status-pass" : "answer-status-fail"}`,
      answer.passed ? "Pass" : "Fail",
    ),
  );
  card.append(header);
  card.append(element("p", "answer-reason", answer.reason || answer.status || "No score detail"));

  const hasContent = Boolean(answer.content.trim());
  const response = element("div", `answer-copy markdown-body${hasContent ? "" : " answer-copy-empty"}`);
  if (hasContent) {
    response.append(renderMarkdown(answer.content));
  } else {
    response.append(element("p", "", "No text response."));
  }
  card.append(response);
  if (hasContent) {
    const raw = element("details", "answer-details answer-raw");
    raw.append(element("summary", "", "Raw Markdown"));
    const renderRawMarkdown = () => {
      if (!raw.open) return;
      raw.append(element("pre", "answer-json", answer.content));
      raw.removeEventListener("toggle", renderRawMarkdown);
    };
    raw.addEventListener("toggle", renderRawMarkdown);
    card.append(raw);
  }
  if (answer.tool_calls.length) {
    const details = element("details", "answer-details");
    details.append(element("summary", "", `Tool calls (${answer.tool_calls.length})`));
    details.append(jsonBlock(answer.tool_calls, "No tool calls."));
    card.append(details);
  }
  return card;
}

function renderAnswerCase(caseData, modelById) {
  const article = element("article", "answer-case");
  const header = element("div", "answer-case-header");
  header.append(element("p", "answer-case-id", caseData.id));
  const passed = caseData.answers.filter((answer) => answer.passed).length;
  header.append(element("p", "answer-case-score", `${passed} / ${caseData.answers.length} models passed`));
  article.append(header);

  const prompt = element("div", "answer-prompt");
  prompt.append(element("span", "answer-label", "User prompt"));
  prompt.append(element("p", "", questionText(caseData.question) || "No prompt text."));
  article.append(prompt);

  const inputs = element("div", "answer-inputs");
  const functions = Array.isArray(caseData.functions) ? caseData.functions : [];
  const functionDetails = element("details", "answer-details");
  functionDetails.append(
    element(
      "summary",
      "",
      functions.length
        ? `Translated function and parameter descriptions (${functions.length})`
        : "No functions supplied",
    ),
  );
  functionDetails.append(jsonBlock(functions, "No functions supplied for this case."));
  inputs.append(functionDetails);
  if (caseData.ground_truth != null) {
    const expectedDetails = element("details", "answer-details");
    expectedDetails.append(element("summary", "", "Expected tool call"));
    expectedDetails.append(jsonBlock(caseData.ground_truth, "No expected tool call."));
    inputs.append(expectedDetails);
  }
  article.append(inputs);

  const grid = element("div", "model-answer-grid");
  caseData.answers.forEach((answer) => grid.append(renderAnswerCard(answer, modelById)));
  article.append(grid);
  return article;
}

function filteredAnswerCases() {
  const needle = answerState.search.trim().toLocaleLowerCase();
  return answerState.cases.filter((caseData) => {
    const allPassed = caseData.answers.every((answer) => answer.passed);
    if (answerState.result === "failed" && allPassed) return false;
    if (answerState.result === "passed" && !allPassed) return false;
    if (!needle) return true;
    return answerSearchText.get(caseData).includes(needle);
  });
}

function renderAnswerBrowser() {
  const container = document.querySelector("#answer-cases");
  const modelById = new Map(
    answerState.manifest.models.map((model) => [model.model_id, model.model]),
  );
  const filtered = filteredAnswerCases();
  const pageCount = Math.max(1, Math.ceil(filtered.length / ANSWERS_PER_PAGE));
  answerState.page = Math.min(answerState.page, pageCount);
  const start = (answerState.page - 1) * ANSWERS_PER_PAGE;
  const visible = filtered.slice(start, start + ANSWERS_PER_PAGE);
  container.replaceChildren();
  visible.forEach((caseData) => container.append(renderAnswerCase(caseData, modelById)));
  if (!visible.length) {
    container.append(element("p", "error-state", "No cases match these filters."));
  }

  document.querySelector("#answer-count").textContent =
    `${filtered.length.toLocaleString("en-US")} of ${answerState.cases.length.toLocaleString("en-US")} cases`;
  document.querySelector("#answer-page").textContent = `Page ${answerState.page} of ${pageCount}`;
  document.querySelector("#answer-previous").disabled = answerState.page === 1;
  document.querySelector("#answer-next").disabled = answerState.page === pageCount;
}

function showAnswerBrowserError(message) {
  answerState.cases = [];
  answerState.page = 1;
  document.querySelector("#answer-cases").replaceChildren(element("p", "error-state", message));
  document.querySelector("#answer-count").textContent = "0 of 0 cases";
  document.querySelector("#answer-page").textContent = "Unavailable";
  document.querySelector("#answer-previous").disabled = true;
  document.querySelector("#answer-next").disabled = true;
  document.querySelector("#answer-download").removeAttribute("href");
}

async function fetchAnswerJson(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), ANSWER_FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

async function loadAnswerCategory(categoryId) {
  const category = answerState.manifest.categories.find((item) => item.id === categoryId);
  if (!category) throw new Error(`Unknown answer category: ${categoryId}`);
  const loadSequence = ++answerLoadSequence;
  const manifestUrl = new URL(ANSWERS_URL, window.location.href);
  const categoryUrl = new URL(category.file, manifestUrl);
  if (!answerCategoryCache.has(categoryId)) {
    const request = fetchAnswerJson(categoryUrl)
      .then((data) => {
        data.cases.forEach((caseData) => {
          answerSearchText.set(caseData, JSON.stringify(caseData).toLocaleLowerCase());
        });
        return data;
      })
      .catch((error) => {
        answerCategoryCache.delete(categoryId);
        throw error;
      });
    answerCategoryCache.set(categoryId, request);
  }
  let data;
  try {
    data = await answerCategoryCache.get(categoryId);
  } catch (error) {
    if (loadSequence !== answerLoadSequence) return false;
    throw error;
  }
  if (loadSequence !== answerLoadSequence) return false;
  answerState.cases = data.cases;
  answerState.page = 1;
  document.querySelector("#answer-download").href = categoryUrl.href;
  renderAnswerBrowser();
  return true;
}

async function initialiseAnswers() {
  try {
    answerState.manifest = await fetchAnswerJson(ANSWERS_URL);
    const select = document.querySelector("#answer-category");
    answerState.manifest.categories.forEach((category) => {
      const option = element(
        "option",
        "",
        `${CATEGORY_COPY[category.id]?.label || category.id} (${category.count})`,
      );
      option.value = category.id;
      select.append(option);
    });
    const requested = new URLSearchParams(window.location.search).get("answers");
    const initialCategory = answerState.manifest.categories.some((item) => item.id === requested)
      ? requested
      : "chatable";
    select.value = initialCategory;
    select.addEventListener("change", async () => {
      const requestedCategory = select.value;
      const url = new URL(window.location);
      url.searchParams.set("answers", requestedCategory);
      window.history.replaceState({}, "", url);
      try {
        await loadAnswerCategory(requestedCategory);
      } catch (error) {
        if (select.value !== requestedCategory) return;
        showAnswerBrowserError("This answer category could not be loaded.");
        console.error("Answer category load failed", error);
      }
    });
    document.querySelector("#answer-result").addEventListener("change", (event) => {
      answerState.result = event.target.value;
      answerState.page = 1;
      renderAnswerBrowser();
    });
    document.querySelector("#answer-search").addEventListener("input", (event) => {
      clearTimeout(answerSearchTimer);
      answerSearchTimer = setTimeout(() => {
        answerState.search = event.target.value;
        answerState.page = 1;
        renderAnswerBrowser();
      }, 120);
    });
    document.querySelector("#answer-previous").addEventListener("click", () => {
      answerState.page -= 1;
      renderAnswerBrowser();
      document.querySelector("#answer-browser").scrollIntoView();
    });
    document.querySelector("#answer-next").addEventListener("click", () => {
      answerState.page += 1;
      renderAnswerBrowser();
      document.querySelector("#answer-browser").scrollIntoView();
    });
    const loadInitialCategory = async () => {
      await loadAnswerCategory(initialCategory);
      if (window.location.hash === "#answer-browser") {
        requestAnimationFrame(() => document.querySelector("#answer-browser").scrollIntoView());
      }
    };
    if (requested || window.location.hash === "#answer-browser" || !("IntersectionObserver" in window)) {
      await loadInitialCategory();
    } else {
      const observer = new IntersectionObserver(
        (entries) => {
          if (!entries.some((entry) => entry.isIntersecting)) return;
          observer.disconnect();
          loadInitialCategory().catch((error) => {
            showAnswerBrowserError("The raw model answers could not be loaded.");
            console.error("Answer browser load failed", error);
          });
        },
        { rootMargin: "600px" },
      );
      observer.observe(document.querySelector("#answer-browser"));
    }
  } catch (error) {
    showAnswerBrowserError("The raw model answers could not be loaded.");
    console.error("Answer browser load failed", error);
  }
}

function labelBlock(title, sub) {
  const label = element("div", "model-label");
  label.append(element("strong", "", title));
  label.append(element("span", "", sub));
  return label;
}

function renderLatencyBars(container, rows, color) {
  container.replaceChildren();
  const max = Math.max(...rows.map((row) => row.value)) || 1;
  rows.forEach((row) => {
    const line = element("div", "leaderboard-row");
    line.append(labelBlock(row.title, row.sub));
    line.append(barTrack(row.value / max, color, row.aria));
    line.append(element("div", "bar-value", row.display));
    container.append(line);
  });
  requestAnimationFrame(() => animateBars(container));
}

function renderLatency(data) {
  const number = (value) => Number(value).toLocaleString("en-US");
  document.querySelector("#latency-model").textContent = data.model;
  document.querySelector("#latency-host").textContent = data.host;

  document.querySelector("#lat-ttft").textContent = `${number(data.headline.ttft_ms)} ms`;
  document.querySelector("#lat-decode").textContent = `${number(data.headline.decode_tok_s)} tok/s`;
  document.querySelector("#lat-peak").textContent = `${number(data.headline.peak_agg_tok_s)} tok/s`;
  document.querySelector("#lat-sweet").textContent = `${data.headline.sweet_spot}×`;

  renderLatencyBars(
    document.querySelector("#latency-length-chart"),
    data.by_length.map((point) => ({
      title: `${number(point.tokens)} tokens`,
      sub: `${number(point.total_ms)} ms total · TTFT ${number(point.ttft_ms)} ms`,
      value: point.decode_tok_s,
      display: `${Math.round(point.decode_tok_s)} tok/s`,
      aria: `${point.tokens} tokens: ${Math.round(point.decode_tok_s)} tokens per second`,
    })),
    "#6ee7b7",
  );

  renderLatencyBars(
    document.querySelector("#latency-concurrency-chart"),
    data.by_concurrency.map((point) => ({
      title: `${point.concurrency} concurrent`,
      sub: `mean TTFT ${number(point.ttft_ms)} ms`,
      value: point.agg_tok_s,
      display: `${number(point.agg_tok_s)} tok/s`,
      aria: `${point.concurrency} concurrent requests: ${point.agg_tok_s} aggregate tokens per second`,
    })),
    "#c8ff61",
  );

  const sweet = data.by_concurrency.find((point) => point.concurrency === data.headline.sweet_spot)
    || data.by_concurrency[0];
  document.querySelector("#latency-insight").textContent =
    `${data.model} clears ~${number(data.headline.decode_tok_s)} tok/s single-stream and peaks near `
    + `${number(data.headline.peak_agg_tok_s)} tok/s around ${data.headline.sweet_spot} concurrent requests — `
    + `where time to first token is still ~${number(sweet.ttft_ms)} ms. Beyond that, latency climbs without more throughput.`;

  const body = document.querySelector("#latency-table-body");
  body.replaceChildren();
  data.by_concurrency.forEach((point) => {
    const row = document.createElement("tr");
    row.append(element("td", "", `${point.concurrency}×`));
    row.append(element("td", "", `${number(point.agg_tok_s)} tok/s`));
    row.append(element("td", "", `${number(point.ttft_ms)} ms`));
    row.append(element("td", "", String(point.failed)));
    body.append(row);
  });
}

async function initialiseLatency() {
  try {
    const response = await fetch(LATENCY_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderLatency(await response.json());
  } catch (error) {
    const chart = document.querySelector("#latency-length-chart");
    if (chart) {
      chart.replaceChildren(
        element("p", "error-state", "The serving-speed data could not be loaded."),
      );
    }
    console.error("Latency data load failed", error);
  }
}

function showLoadError(error) {
  const chart = document.querySelector("#overall-chart");
  chart.replaceChildren(
    element("p", "error-state", "The benchmark data could not be loaded. Refresh or view the source results on GitHub."),
  );
  console.error("Benchmark data load failed", error);
}

async function initialise() {
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const colorIndexByModelId = new Map(
      data.results.map((result, index) => [result.model_id, index]),
    );
    const requestedCategory = new URLSearchParams(window.location.search).get("category");
    const selectedCategory = data.categories.includes(requestedCategory)
      ? requestedCategory
      : data.categories[0];
    renderSummary(data);
    renderOverall(data.results);
    renderControls(data.results, colorIndexByModelId, data.categories, selectedCategory);
    renderCategory(data.results, colorIndexByModelId, selectedCategory);
    renderTable(data.results);
  } catch (error) {
    showLoadError(error);
  }
  await initialiseAnswers();
}

initialise();
initialiseLatency();

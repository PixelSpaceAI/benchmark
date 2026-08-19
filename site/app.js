const DATA_URL = document.body.dataset.resultsUrl || "./data/comparison.json";

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
}

initialise();

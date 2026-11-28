(() => {
  const subjects = JSON.parse(document.getElementById("notes-data").textContent);
  const topics = subjects.flatMap((subject) =>
    subject.groups.flatMap((group) =>
      group.topics.map((topic) => ({
        ...topic,
        subject: subject.name,
        group: group.title,
      })),
    ),
  );
  const topicMap = new Map(topics.map((topic) => [topic.id, topic]));
  const storageKey = "fakao-notes-annotations-v1";
  const navigation = document.getElementById("navigation");
  const search = document.getElementById("search");
  const results = document.getElementById("search-results");
  const articleToc = document.getElementById("article-toc");
  const article = document.getElementById("article");
  const welcome = document.getElementById("welcome");
  const annotationPanel = document.getElementById("annotation-panel");
  const annotationList = document.getElementById("annotation-list");
  const selectionBar = document.getElementById("selection-bar");
  const annotationModal = document.getElementById("annotation-modal");
  const annotationInput = document.getElementById("annotation-input");
  let annotations = {};
  let currentTopic = null;
  let pendingQuote = "";
  let searchTimer;

  const escapeHtml = (value) =>
    String(value).replace(/[&<>"']/g, (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
    );

  function showMessage(message) {
    let toast = document.querySelector(".toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "toast";
      toast.setAttribute("role", "status");
      document.body.append(toast);
    }
    toast.textContent = message;
    toast.classList.add("visible");
    window.clearTimeout(showMessage.timer);
    showMessage.timer = window.setTimeout(() => toast.classList.remove("visible"), 3200);
  }

  function loadAnnotations() {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("批注数据格式无效");
        }
        annotations = parsed;
      }
    } catch (error) {
      showMessage(`无法读取本地批注：${error.message}`);
    }
  }

  function saveAnnotations() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(annotations));
      updateAnnotationCount();
      return true;
    } catch (error) {
      showMessage(`批注未能保存到此浏览器：${error.message}`);
      return false;
    }
  }

  function getTopicNotes(topicId) {
    return Array.isArray(annotations[topicId]) ? annotations[topicId] : [];
  }

  function updateAnnotationCount() {
    const count = currentTopic ? getTopicNotes(currentTopic.id).length : 0;
    const button = document.getElementById("show-annotations");
    if (button) button.textContent = `批注 ${count}`;
  }

  function renderArticleToc(topic) {
    const body = article.querySelector(".article-body");
    const entries = [...body.querySelectorAll("li")]
      .filter(
        (item) =>
          !item.parentElement.closest("li") &&
          !item.closest(".callout, .tree-diagram"),
      )
      .map((item) => {
        const clone = item.cloneNode(true);
        clone.querySelectorAll("ol, ul, figure, table").forEach((element) =>
          element.remove(),
        );
        clone.querySelectorAll("br").forEach((element) =>
          element.replaceWith(" "),
        );
        const text = clone.textContent.replace(/\s+/g, " ").trim();
        const period = text.indexOf("。");
        return {
          item,
          label: (period < 0 ? text : text.slice(0, period)).trim(),
        };
      })
      .filter(({ label }) => label);

    articleToc.replaceChildren();
    if (!entries.length) {
      articleToc.hidden = true;
      return;
    }

    const title = document.createElement("h2");
    title.className = "article-toc-title";
    title.textContent = '要点';
    const list = document.createElement("ol");
    list.className = "article-toc-list";
    entries.forEach(({ item, label }) => {
      item.classList.add("toc-target");
      const listItem = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.title = label;
      button.addEventListener("click", () =>
        item.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
      listItem.append(button);
      list.append(listItem);
    });
    articleToc.append(title, list);
    articleToc.hidden = false;
  }

  function renderNavigation() {
    navigation.replaceChildren();
    subjects.forEach((subject, subjectIndex) => {
      const subjectDetails = document.createElement("details");
      subjectDetails.className = "subject-nav";
      subjectDetails.open = subjectIndex === 0;
      const subjectSummary = document.createElement("summary");
      subjectSummary.innerHTML = `<span class="subject-number">${String(subjectIndex + 1).padStart(2, "0")}</span><span>${escapeHtml(subject.name)}</span><span class="chevron">⌄</span>`;
      subjectDetails.append(subjectSummary);
      const groupContainer = document.createElement("div");
      groupContainer.className = "group-nav";
      subject.groups.forEach((group) => {
        const groupDetails = document.createElement("details");
        groupDetails.className = "group-item";
        groupDetails.open = subject.groups.length === 1;
        const groupSummary = document.createElement("summary");
        groupSummary.textContent = group.title;
        groupDetails.append(groupSummary);
        const topicList = document.createElement("div");
        topicList.className = "topic-list";
        group.topics.forEach((topic) => {
          const button = document.createElement("button");
          button.className = "topic-link";
          button.dataset.topicId = topic.id;
          button.textContent = topic.title;
          button.addEventListener("click", () => openTopic(topic.id));
          topicList.append(button);
        });
        if (subject.groups.length === 1 && group.title === subject.name) {
          groupContainer.append(topicList);
        } else {
          groupDetails.append(topicList);
          groupContainer.append(groupDetails);
        }
      });
      subjectDetails.append(groupContainer);
      navigation.append(subjectDetails);
    });
  }

  function escapeRegex(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function highlightCurrentSearch() {
    const query = search.value.trim();
    if (!query) return;
    const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    const expression = new RegExp(escapeRegex(query), "ig");
    nodes.forEach((node) => {
      if (!node.nodeValue || !expression.test(node.nodeValue)) {
        expression.lastIndex = 0;
        return;
      }
      expression.lastIndex = 0;
      const fragment = document.createDocumentFragment();
      let cursor = 0;
      let match;
      while ((match = expression.exec(node.nodeValue))) {
        fragment.append(document.createTextNode(node.nodeValue.slice(cursor, match.index)));
        const mark = document.createElement("mark");
        mark.className = "search-highlight";
        mark.textContent = match[0];
        fragment.append(mark);
        cursor = match.index + match[0].length;
      }
      fragment.append(document.createTextNode(node.nodeValue.slice(cursor)));
      node.replaceWith(fragment);
    });
  }

  function openTopic(topicId, options = {}) {
    const topic = topicMap.get(topicId);
    if (!topic) return;
    currentTopic = topic;
    const activeLink = [...document.querySelectorAll(".topic-link")].find(
      (button) => button.dataset.topicId === topic.id,
    );
    activeLink?.closest(".subject-nav")?.setAttribute("open", "");
    activeLink?.closest(".group-item")?.setAttribute("open", "");
    welcome.hidden = true;
    article.hidden = false;
    results.hidden = true;
    annotationPanel.hidden = true;
    article.innerHTML = `
      <div class="article-meta"><span>${escapeHtml(topic.subject)}</span><span class="meta-divider">/</span><span>${escapeHtml(topic.group)}</span></div>
      <h1 class="article-title">${escapeHtml(topic.title)}</h1>
      <div class="article-tools"><span>选中正文，即可添加个人批注</span><button id="show-annotations" class="toolbar-button">批注 ${getTopicNotes(topic.id).length}</button></div>
      <div class="article-body">${topic.html}</div>
      <section class="article-annotations"><h2>本篇批注 <span>${getTopicNotes(topic.id).length}</span></h2><div id="inline-annotations"></div></section>`;
    renderArticleToc(topic);
    document.querySelectorAll(".topic-link").forEach((button) => {
      button.classList.toggle("active", button.dataset.topicId === topic.id);
    });
    document.getElementById("show-annotations").addEventListener("click", showAnnotations);
    renderAnnotations();
    const hash = `#${encodeURIComponent(topic.id)}`;
    if (window.location.hash !== hash) history.replaceState(null, "", hash);
    if (options.scroll !== false) window.scrollTo({ top: 0, behavior: "smooth" });
    if (options.highlight) highlightCurrentSearch();
    closeMobileNavigation();
  }

  function escapeRegExp(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function excerptFor(topic, query) {
    const text = (topic?.text ?? "").replace(/\s+/g, " ").trim();
    const q = (query ?? "").trim();
    if (!q) return text.slice(0, 100);

    const lowerText = text.toLocaleLowerCase();
    const lowerQuery = q.toLocaleLowerCase();
    const index = lowerText.indexOf(lowerQuery);

    if (index < 0) {
      return text.slice(0, 100) + (text.length > 100 ? "…" : "");
    }

    const start = Math.max(0, index - 34);
    const end = Math.min(text.length, index + q.length + 66);
    const snippet = text.slice(start, end);

    const matcher = new RegExp(escapeRegExp(q), "gi");
    const highlighted = snippet.replace(
      matcher,
      (match) => `<span class="matched">${match}</span>`
    );

    return `${start > 0 ? "…" : ""}${highlighted}${end < text.length ? "…" : ""}`;
  }

  function runSearch() {
    const query = search.value.trim();
    if (query.length < 1) {
      results.hidden = true;
      results.replaceChildren();
      articleToc.hidden = !currentTopic || articleToc.children.length === 0;
      article.hidden = !currentTopic;
      welcome.hidden = Boolean(currentTopic);
      return;
    }
    const matches = topics.filter((topic) =>
      `${topic.title} ${topic.subject} ${topic.group} ${topic.text}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
    );
    results.hidden = false;
    articleToc.hidden = true;
    article.hidden = true;
    welcome.hidden = true;
    annotationPanel.hidden = true;
    const shown = matches.slice(0, 120);
    results.innerHTML = `<div class="results-heading"><div><span class="eyebrow">SEARCH RESULTS</span><h1>“${escapeHtml(query)}”</h1></div><span class="result-count">${matches.length} 篇笔记${matches.length > shown.length ? ` · 显示前 ${shown.length} 篇` : ""}</span></div>${
      shown.length
        ? `<div class="result-list">${shown.map((topic) => `<button class="result-card" data-topic-id="${escapeHtml(topic.id)}"><span class="result-meta">${escapeHtml(topic.subject)} <span>/</span> ${escapeHtml(topic.group)}</span><strong>${excerptFor({text: topic.title}, query)}</strong><span class="result-excerpt">${excerptFor(topic, query)}</span><span class="result-arrow">↗</span></button>`).join("")}</div>`
        : '<div class="empty-state">没有找到匹配内容，试试更短的关键词。</div>'
    }`;
    results.querySelectorAll(".result-card").forEach((button) => {
      button.addEventListener("click", () => {
        openTopic(button.dataset.topicId, { highlight: true });
        search.blur();
      });
    });
  }

  function renderAnnotations() {
    if (!currentTopic) return;
    const notes = getTopicNotes(currentTopic.id);
    const inline = document.getElementById("inline-annotations");
    if (inline) {
      inline.replaceChildren();
      if (!notes.length) {
        inline.innerHTML = '<p class="no-annotations">选中正文中的一段内容，添加你的第一条批注。</p>';
      } else {
        notes.forEach((note, index) => inline.append(createAnnotationCard(note, index)));
      }
    }
    annotationList.replaceChildren();
    if (!notes.length) {
      annotationList.innerHTML = '<div class="empty-annotations">这篇笔记还没有批注。</div>';
    } else {
      notes.forEach((note, index) => annotationList.append(createAnnotationCard(note, index)));
    }
    updateAnnotationCount();
  }

  function createAnnotationCard(note, index) {
    const card = document.createElement("div");
    card.className = "annotation-card";
    const quote = document.createElement("button");
    quote.className = "annotation-quote";
    quote.textContent = `“${note.quote}”`;
    quote.title = "定位原文";
    quote.addEventListener("click", () => locateQuote(note.quote));
    const body = document.createElement("p");
    body.className = "annotation-text";
    body.textContent = note.text;
    const footer = document.createElement("div");
    footer.className = "annotation-footer";
    const date = document.createElement("time");
    date.textContent = note.createdAt ? new Date(note.createdAt).toLocaleDateString() : "";
    const remove = document.createElement("button");
    remove.className = "delete-annotation";
    remove.textContent = "删除";
    remove.addEventListener("click", () => {
      annotations[currentTopic.id].splice(index, 1);
      if (!annotations[currentTopic.id].length) delete annotations[currentTopic.id];
      if (saveAnnotations()) renderAnnotations();
    });
    footer.append(date, remove);
    card.append(quote, body, footer);
    return card;
  }

  function locateQuote(quote) {
    const walker = document.createTreeWalker(article.querySelector(".article-body"), NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const index = node.nodeValue.indexOf(quote);
      if (index < 0) continue;
      const range = document.createRange();
      range.setStart(node, index);
      range.setEnd(node, index + quote.length);
      const mark = document.createElement("mark");
      mark.className = "annotation-highlight";
      try {
        range.surroundContents(mark);
        mark.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      } catch {
        node.parentElement.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
    }
    showMessage("原文没有找到，可能内容跨越多个格式区域。");
  }

  function showAnnotations() {
    annotationPanel.hidden = false;
    annotationPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function closeMobileNavigation() {
    document.getElementById("sidebar").classList.remove("mobile-open");
  }

  document.getElementById("welcome-stats").textContent =
    `${subjects.length} 个科目 · ${topics.length} 篇专题 · 支持全文搜索与本地批注`;
  renderNavigation();
  loadAnnotations();

  document.getElementById("close-annotations").addEventListener("click", () => {
    annotationPanel.hidden = true;
  });
  document.getElementById("menu-button").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("mobile-open");
  });
  document.getElementById("annotate-selection").addEventListener("click", () => {
    document.getElementById("quoted-text").textContent = `“${pendingQuote}”`;
    annotationInput.value = "";
    annotationModal.hidden = false;
    annotationInput.focus();
  });
  const closeModal = () => {
    annotationModal.hidden = true;
    selectionBar.hidden = true;
  };
  document.getElementById("cancel-annotation").addEventListener("click", closeModal);
  document.getElementById("discard-annotation").addEventListener("click", closeModal);
  annotationModal.addEventListener("click", (event) => {
    if (event.target === annotationModal) closeModal();
  });
  document.getElementById("annotation-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = annotationInput.value.trim();
    if (!currentTopic || !pendingQuote || !text) return;
    annotations[currentTopic.id] ??= [];
    annotations[currentTopic.id].push({
      quote: pendingQuote,
      text,
      createdAt: new Date().toISOString(),
    });
    if (saveAnnotations()) {
      renderAnnotations();
      showAnnotations();
      closeModal();
      showMessage("批注已保存在此浏览器。");
    }
  });
  document.addEventListener("mouseup", () => {
    window.setTimeout(() => {
      const selection = window.getSelection();
      const selectedText = selection?.toString().trim() ?? "";
      if (
        selectedText.length > 0 &&
        selectedText.length < 1200 &&
        selection.anchorNode &&
        article.querySelector(".article-body")?.contains(selection.anchorNode)
      ) {
        pendingQuote = selectedText;
        document.getElementById("selection-preview").textContent =
          `已选中：${selectedText.slice(0, 58)}${selectedText.length > 58 ? "…" : ""}`;
        selectionBar.hidden = false;
      } else {
        selectionBar.hidden = true;
      }
    }, 0);
  });
  search.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(runSearch, 120);
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      search.focus();
      search.select();
    }
    if (event.key === "Escape") {
      closeModal();
      closeMobileNavigation();
      search.value = "";
      runSearch();
    }
  });

  document.getElementById("export-notes").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify({ version: 1, annotations }, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "法考笔记-批注备份.json";
    link.click();
    URL.revokeObjectURL(url);
  });

  document.getElementById("import-notes").addEventListener("change", async (event) => {
    const [file] = event.target.files;
    if (!file) return;
    try {
      const imported = JSON.parse(await file.text());
      const data = imported?.annotations ?? imported;
      if (!data || typeof data !== "object" || Array.isArray(data)) {
        throw new Error("文件中没有有效的批注数据");
      }
      Object.entries(data).forEach(([topicId, notes]) => {
        if (!topicMap.has(topicId) || !Array.isArray(notes)) return;
        const existing = getTopicNotes(topicId);
        annotations[topicId] = [...existing, ...notes.filter(
          (note) => note && typeof note.quote === "string" && typeof note.text === "string",
        )];
      });
      if (saveAnnotations()) {
        if (currentTopic) renderAnnotations();
        showMessage("批注导入完成。");
      }
    } catch (error) {
      showMessage(`批注导入失败：${error.message}`);
    } finally {
      event.target.value = "";
    }
  });

  document.getElementById("branch-select").addEventListener("change", (event) => {
    const select = event.currentTarget;
    if (select.value) {
      window.location.assign(select.value + window.location.hash);
    } else {
      select.selectedIndex = Array.from(select.options).findIndex(
        (option) => option.defaultSelected,
      );
    }
  });

  const initialId = decodeURIComponent(window.location.hash.slice(1));
  if (topicMap.has(initialId)) openTopic(initialId, { scroll: false });
  else {
    const firstTopic = topics[0];
    if (firstTopic) openTopic(firstTopic.id, { scroll: false });
  }
})();

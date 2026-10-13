(function runLeadMining1688Bookmarklet() {
  if (window.__leadMining1688Running) {
    alert("1688采集助手正在运行，请先在右下角点停止或等待完成。");
    return;
  }

  const SCRIPT_VERSION = "2026-06-13-v3";
  const ENDPOINT = "http://127.0.0.1:8000/api/page-snapshots/1688";
  const MAX_TOTAL_LIMIT = 1200;
  const MAX_PAGE_LIMIT = 100;
  const DEFAULT_DELAY_SECONDS = 5;
  const BLOCKED_TEXT_PATTERN = /验证码|安全验证|拖动下方滑块|访问被拒绝|访问过于频繁|遇到问题|请完成验证|当前操作存在风险|亲，请拖动|亲，访问被拒绝/;
  const COMPANY_PATTERN = /([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,70}(?:有限责任公司|股份有限公司|集团有限公司|有限公司|商行|经营部|工作室|工厂))/g;
  const INVALID_COMPANY_PATTERN = /^(?:找货源|找工厂|找供应商|工业品|找服务|找代发|采购车|官方服务|我的阿里|下载插件|消息|我的订单)$/;
  const state = { stopped: false, previewIframe: null };

  window.__leadMining1688Running = true;

  function clean(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function is1688Page() {
    return /(^|\.)1688\.com$|(^|\.)alibaba\.com$/.test(location.hostname);
  }

  function hasMojibake(text) {
    return /锟|�|茂驴陆|閿|閲|楠|鐢|鑱|绾|鍏|涓|宸|囚|ョ|链将囚|ョ配|宸ャ|将囚/.test(text || "");
  }

  function safeInt(value, fallback, min, max) {
    const parsed = parseInt(value, 10);
    if (!Number.isFinite(parsed)) {
      return fallback;
    }
    return Math.max(min, Math.min(parsed, max));
  }

  function promptNumber(label, defaultValue, min, max) {
    const value = prompt(label, String(defaultValue));
    if (value === null) {
      throw new Error("用户取消采集");
    }
    return safeInt(value, defaultValue, min, max);
  }

  function decodeQueryValue(rawValue) {
    if (!rawValue) {
      return "";
    }
    const normalizedValue = rawValue.replace(/\+/g, "%20");
    try {
      const utf8Text = decodeURIComponent(normalizedValue);
      if (utf8Text && !hasMojibake(utf8Text)) {
        return utf8Text;
      }
    } catch (error) {
      // Try GB18030 below.
    }
    try {
      const byteList = [];
      normalizedValue.replace(/%([0-9a-fA-F]{2})|./g, (match, hex) => {
        byteList.push(hex ? parseInt(hex, 16) : match.charCodeAt(0));
        return "";
      });
      return new TextDecoder("gb18030").decode(new Uint8Array(byteList));
    } catch (error) {
      return normalizedValue;
    }
  }

  function getRawQueryValue(name, urlText) {
    const url = urlText || location.href;
    const queryIndex = url.indexOf("?");
    if (queryIndex < 0) {
      return "";
    }
    const queryText = url.slice(queryIndex);
    const match = queryText.match(new RegExp(`[?&]${name}=([^&]*)`));
    return match ? decodeQueryValue(match[1]) : "";
  }

  function getSourceKeyword(doc) {
    const input = doc.querySelector('input[placeholder*="搜索"], input[type="search"], input[type="text"]');
    const urlKeyword = getRawQueryValue("keywords") || getRawQueryValue("q") || getRawQueryValue("key");
    const titleKeyword = (doc.title || document.title || "").split("-")[0];
    const value = clean((input && input.value) || urlKeyword || titleKeyword || "1688当前页面");
    return hasMojibake(value) ? "1688当前页面" : value.slice(0, 100);
  }

  function normalizeSearchKeyword(keyword) {
    return clean(keyword)
      .replace(/[，、；;]+/g, ",")
      .split(",")
      .map((item) => clean(item))
      .filter(Boolean)[0] || "";
  }

  function promptCleanKeyword(defaultKeyword) {
    let keyword = normalizeSearchKeyword(defaultKeyword);
    if (!keyword || hasMojibake(keyword)) {
      keyword = "";
    }
    const input = prompt("请输入准确搜索词（不要使用乱码；建议单个词，例如：服装工厂 / 女装批发 / 化妆品工厂）", keyword || "服装工厂");
    if (input === null) {
      throw new Error("用户取消采集");
    }
    const cleanKeyword = normalizeSearchKeyword(input);
    if (!cleanKeyword || hasMojibake(cleanKeyword)) {
      throw new Error(`搜索词仍疑似乱码：${input}。请重新复制中文关键词后再运行。`);
    }
    return cleanKeyword.slice(0, 50);
  }

  function buildCleanFactorySearchUrl(keyword, pageNumber) {
    const url = new URL("https://s.1688.com/company/pc/factory_search.htm");
    url.searchParams.set("keywords", keyword);
    url.searchParams.set("province", "广东");
    url.searchParams.set("beginPage", String(pageNumber));
    return url.href;
  }

  function getCurrentPageNumber() {
    const url = new URL(location.href);
    for (const name of ["beginPage", "pageNo", "page"]) {
      const value = safeInt(url.searchParams.get(name), 0, 0, MAX_PAGE_LIMIT);
      if (value > 0) {
        return value;
      }
    }
    const activeTextList = Array.from(document.querySelectorAll("button, a, span, div"))
      .filter((element) => {
        const text = clean(element.innerText);
        if (!/^\d{1,3}$/.test(text)) {
          return false;
        }
        const style = getComputedStyle(element);
        const classText = String(element.className || "");
        return /active|current|selected|pagination-item-active/.test(classText)
          || /rgb\(255,\s*64,\s*0\)|#ff4000|orange/i.test(style.backgroundColor + style.color);
      })
      .map((element) => safeInt(element.innerText, 0, 0, MAX_PAGE_LIMIT))
      .filter(Boolean);
    return activeTextList[0] || 1;
  }

  function getTotalPageNumber(doc) {
    const pageText = clean((doc.body && doc.body.innerText) || "");
    const match = pageText.match(/共\s*(\d{1,4})\s*页/);
    return match ? safeInt(match[1], 1, 1, MAX_PAGE_LIMIT) : MAX_PAGE_LIMIT;
  }

  function buildPageUrl(pageNumber) {
    const url = new URL(location.href);
    let pageParamName = ["beginPage", "pageNo", "page"].find((name) => url.searchParams.has(name));
    if (!pageParamName) {
      pageParamName = /s\.1688\.com$/.test(url.hostname) ? "beginPage" : "page";
    }
    url.searchParams.set(pageParamName, String(pageNumber));
    return url.href;
  }

  function extractCompanyName(text) {
    COMPANY_PATTERN.lastIndex = 0;
    const match = COMPANY_PATTERN.exec(text);
    if (!match) {
      return "";
    }
    return clean(match[1]);
  }

  function countCompanyName(text) {
    COMPANY_PATTERN.lastIndex = 0;
    let count = 0;
    while (COMPANY_PATTERN.exec(text)) {
      count += 1;
      if (count > 3) {
        return count;
      }
    }
    return count;
  }

  function dedupeTextList(textList) {
    const resultList = [];
    const seenTextSet = new Set();
    for (const text of textList) {
      const cleanText = clean(text).replace(/\s+/g, "");
      if (!cleanText || seenTextSet.has(cleanText)) {
        continue;
      }
      seenTextSet.add(cleanText);
      resultList.push(cleanText);
    }
    return resultList;
  }

  function extractPhoneList(text) {
    const phoneList = [];
    const sourceText = String(text || "");
    const mobileMatchList = sourceText.match(/(?<!\d)1[3-9]\d{9}(?!\d)/g) || [];
    const landlineMatchList = sourceText.match(/(?<!\d)0\d{2,3}[-\s]?\d{7,8}(?!\d)/g) || [];
    for (const phone of mobileMatchList.concat(landlineMatchList)) {
      phoneList.push(phone.replace(/\s+/g, ""));
    }
    return dedupeTextList(phoneList);
  }

  function extractContactName(doc) {
    const pageText = clean((doc.body && doc.body.innerText) || "");
    const patternList = [
      /(?:联系人|联系卖家|业务联系人|负责人|厂长|销售经理|业务经理)[:：\s]*([\u4e00-\u9fa5A-Za-z\s]{2,16})/,
      /([\u4e00-\u9fa5]\s*[\u4e00-\u9fa5]{1,4})\s*(?:先生|女士|经理|厂长|负责人|销售|业务)/
    ];
    for (const pattern of patternList) {
      const match = pageText.match(pattern);
      if (!match) {
        continue;
      }
      const contactName = clean(match[1]).replace(/\s+/g, "");
      if (contactName.length >= 2 && contactName.length <= 8 && !/电话|在线|联系|立即|负责工厂/.test(contactName)) {
        return contactName;
      }
    }
    return "";
  }

  function extractMainProductText(text) {
    const match = String(text || "").match(/主营[:：]?\s*([^。；;\n]{2,120})/);
    if (!match) {
      return "";
    }
    return clean(match[1].split(/[\u4e00-\u9fa5]{2,4}\s*(?:厂长|经理|负责人)|来样加工|来图加工|加工方式|支持外贸订单|CCC认证|ISO|AA诚信|地址|地图查看|关注|联系人|联系电话|电话来源|电话联系|立即询价|负责工厂|业务联系人|厂长|经理|负责人/)[0]).slice(0, 80);
  }

  function isVisibleElement(element) {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0
      && rect.height > 0
      && style.display !== "none"
      && style.visibility !== "hidden"
      && Number(style.opacity || "1") > 0;
  }

  function findPhoneContactButton() {
    const candidateList = Array.from(document.querySelectorAll("button, a, span, div"))
      .filter((element) => {
        const text = clean(element.innerText);
        return text.length <= 24
          && /电话联系|查看电话|电话号码|拨打电话|电话/.test(text)
          && !/客服电话|联系电话已复制/.test(text)
          && isVisibleElement(element);
      });
    return candidateList.find((element) => /电话联系/.test(clean(element.innerText))) || candidateList[0] || null;
  }

  async function revealDetailPhone(panel) {
    const beforePhoneList = extractPhoneList(document.body ? document.body.innerText : "");
    const phoneButton = findPhoneContactButton();
    if (phoneButton) {
      updatePanel(panel, "正在点击详情页电话联系按钮...");
      phoneButton.scrollIntoView({ block: "center", inline: "center" });
      await sleep(600);
      phoneButton.click();
      await sleep(2200);
      assertPageAllowed(document);
    }
    const afterText = document.body ? document.body.innerText : "";
    return {
      contactName: extractContactName(document),
      phoneList: dedupeTextList(beforePhoneList.concat(extractPhoneList(afterText)))
    };
  }

  function buildDetailPageExtraText(detailInfo) {
    const pageText = clean(document.body ? document.body.innerText : "");
    const companyName = extractCompanyName(pageText);
    const productName = extractMainProductText(pageText) || getSourceKeyword(document);
    const lineList = [];
    if (companyName) {
      lineList.push(`公司名称：${companyName}`);
    }
    if (productName) {
      lineList.push(`主营：${productName}`);
    }
    if (detailInfo.contactName) {
      lineList.push(`联系人：${detailInfo.contactName}`);
    }
    if (detailInfo.phoneList.length > 0) {
      lineList.push(`联系电话：${detailInfo.phoneList.join("；")}`);
      lineList.push("电话来源：1688详情页电话联系公开弹窗");
    }
    lineList.push(`页面地址：${location.href}`);
    return lineList.join("\n");
  }

  function normalizeHref(rawHref, baseUrl) {
    if (!rawHref) {
      return "";
    }
    try {
      return new URL(rawHref, baseUrl || location.href).href;
    } catch (error) {
      return "";
    }
  }

  function collectCardsFromDocument(doc, baseUrl) {
    const selector = [
      'li',
      'div[class*="offer"]',
      'div[class*="company"]',
      'div[class*="supplier"]',
      'div[class*="factory"]',
      'div[class*="card"]',
      'div[class*="item"]',
      'div[class*="list"]',
      'div[class*="search"]'
    ].join(",");
    const nodeList = Array.from(doc.querySelectorAll(selector));
    const seenKeySet = new Set();
    const cardList = [];

    for (const element of nodeList) {
      const text = clean(element.innerText);
      if (text.length < 20 || text.length > 1800) {
        continue;
      }
      const companyName = extractCompanyName(text);
      if (!companyName || INVALID_COMPANY_PATTERN.test(companyName)) {
        continue;
      }
      if (countCompanyName(text) > 3) {
        continue;
      }
      const link = element.querySelector(
        'a[href*="1688.com"], a[href^="//"], a[href*="/offer/"], a[href*="/company/"], a[href*="/factory/"]'
      ) || element.closest("a[href]");
      const href = normalizeHref(link ? link.getAttribute("href") : "", baseUrl);
      const key = `${companyName}|${href || text.slice(0, 80)}`;
      if (seenKeySet.has(key)) {
        continue;
      }
      seenKeySet.add(key);
      cardList.push({ text: text.slice(0, 1200), href });
    }
    return cardList;
  }

  async function scrollDocument(win, doc) {
    const body = doc.body;
    if (!body) {
      return;
    }
    const height = Math.max(body.scrollHeight || 0, doc.documentElement.scrollHeight || 0);
    const stepCount = Math.min(8, Math.max(3, Math.ceil(height / 900)));
    for (let index = 0; index <= stepCount; index += 1) {
      if (state.stopped) {
        return;
      }
      win.scrollTo(0, Math.floor((height * index) / stepCount));
      await sleep(450);
    }
    win.scrollTo(0, 0);
    await sleep(350);
  }

  function assertPageAllowed(doc) {
    const pageText = clean((doc.body && doc.body.innerText) || "").slice(0, 6000);
    if (BLOCKED_TEXT_PATTERN.test(pageText)) {
      throw new Error("1688页面出现验证或访问限制，已停止采集，请人工处理后再继续。");
    }
  }

  function createPanel() {
    const panel = document.createElement("div");
    panel.id = "lead-mining-1688-panel";
    panel.style.cssText = [
      "position:fixed",
      "right:18px",
      "bottom:18px",
      "z-index:2147483647",
      "width:320px",
      "padding:14px",
      "border-radius:10px",
      "background:#0f172a",
      "color:#fff",
      "font:14px/1.6 Microsoft YaHei,Arial,sans-serif",
      "box-shadow:0 18px 45px rgba(15,23,42,.28)"
    ].join(";");
    panel.innerHTML = [
      `<div style="font-weight:700;margin-bottom:6px;">1688采集助手 <span style="font-weight:400;color:#bfdbfe;">${SCRIPT_VERSION}</span></div>`,
      '<div data-role="status">新版已加载：详情页电话 + 可视化翻页。</div>',
      '<button data-role="stop" style="margin-top:10px;height:32px;border:0;border-radius:7px;padding:0 12px;background:#ef4444;color:#fff;cursor:pointer;">停止</button>'
    ].join("");
    panel.querySelector('[data-role="stop"]').addEventListener("click", () => {
      state.stopped = true;
      updatePanel(panel, "已请求停止，当前页处理完会退出。");
    });
    document.body.appendChild(panel);
    return panel;
  }

  function updatePanel(panel, text) {
    const status = panel.querySelector('[data-role="status"]');
    if (status) {
      status.textContent = text;
    }
  }

  function removePreviewIframe() {
    if (state.previewIframe && state.previewIframe.parentElement) {
      state.previewIframe.parentElement.removeChild(state.previewIframe);
    }
    state.previewIframe = null;
  }

  function getPreviewIframe() {
    if (state.previewIframe && state.previewIframe.parentElement) {
      return state.previewIframe;
    }
    const iframe = document.createElement("iframe");
    iframe.setAttribute("title", "1688批量翻页采集预览");
    iframe.style.cssText = [
      "position:fixed",
      "left:18px",
      "top:74px",
      "width:calc(100vw - 380px)",
      "height:calc(100vh - 112px)",
      "z-index:2147483645",
      "border:2px solid #2563eb",
      "border-radius:12px",
      "background:#fff",
      "box-shadow:0 18px 45px rgba(15,23,42,.28)"
    ].join(";");
    document.body.appendChild(iframe);
    state.previewIframe = iframe;
    return iframe;
  }

  async function loadCardsByIframe(url, panel, pageNumber) {
    return new Promise((resolve, reject) => {
      const iframe = getPreviewIframe();
      let isDone = false;
      const timer = window.setTimeout(() => {
        if (isDone) {
          return;
        }
        isDone = true;
        reject(new Error(`第 ${pageNumber} 页加载超时`));
      }, 45000);

      iframe.onload = async () => {
        if (isDone) {
          return;
        }
        try {
          await sleep(2400);
          const win = iframe.contentWindow;
          const doc = iframe.contentDocument || (win && win.document);
          if (!win || !doc || !doc.body) {
            throw new Error(`第 ${pageNumber} 页无法读取`);
          }
          if ((win.location && win.location.href) === "about:blank") {
            return;
          }
          await scrollDocument(win, doc);
          assertPageAllowed(doc);
          const cards = collectCardsFromDocument(doc, url);
          const text = clean(doc.body.innerText).slice(0, 12000);
          isDone = true;
          window.clearTimeout(timer);
          resolve({
            cards,
            pageText: text,
            pageTitle: doc.title || "",
            pageUrl: (win.location && win.location.href) || url
          });
        } catch (error) {
          isDone = true;
          window.clearTimeout(timer);
          reject(error);
        }
      };
      updatePanel(panel, `正在可视化加载第 ${pageNumber} 页...`);
      iframe.src = url;
    });
  }

  async function postSnapshot(payload) {
    const response = await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    return data;
  }

  function buildPayload(options, cards, pageText, pageUrl, pageTitle) {
    return {
      industry: options.industry,
      source_keyword: options.sourceKeyword,
      collect_limit: options.totalLimit,
      page_url: pageUrl || location.href,
      page_title: pageTitle || document.title,
      page_text: clean(pageText || document.body.innerText).slice(0, 300000),
      cards: cards.slice(0, MAX_TOTAL_LIMIT),
      is_qcc_enabled: false,
      qcc_limit: 0
    };
  }

  async function importCurrentPage(panel) {
    const industry = prompt("行业：服装 / 3C数码 / 美妆个护", localStorage.getItem("leadMining1688Industry") || "美妆个护");
    if (industry === null) {
      throw new Error("用户取消采集");
    }
    localStorage.setItem("leadMining1688Industry", industry || "美妆个护");
    const totalLimit = promptNumber("当前页采集上限", 30, 1, MAX_TOTAL_LIMIT);
    updatePanel(panel, "正在滚动加载当前页公开字段...");
    await scrollDocument(window, document);
    assertPageAllowed(document);
    const detailInfo = await revealDetailPhone(panel);
    assertPageAllowed(document);
    const cards = collectCardsFromDocument(document, location.href);
    const options = {
      industry: industry || "美妆个护",
      sourceKeyword: getSourceKeyword(document),
      totalLimit
    };
    updatePanel(panel, `正在导入当前页，识别到 ${cards.length} 张候选卡片...`);
    const enrichedPageText = [
      buildDetailPageExtraText(detailInfo),
      document.body.innerText
    ].filter(Boolean).join("\n\n");
    const data = await postSnapshot(buildPayload(options, cards, enrichedPageText, location.href, document.title));
    alert(`1688当前页导入完成：入库 ${data.lead_count || 0} 条，解析 ${data.parsed_count || 0} 条。`);
  }

  async function importPageBatch(panel) {
    const industry = prompt("行业：服装 / 3C数码 / 美妆个护", localStorage.getItem("leadMining1688Industry") || "美妆个护");
    if (industry === null) {
      throw new Error("用户取消采集");
    }
    localStorage.setItem("leadMining1688Industry", industry || "美妆个护");
    const totalLimit = promptNumber("总采集上限（最多1200，建议先用100测试）", 100, 1, MAX_TOTAL_LIMIT);
    const detectedStartPage = getCurrentPageNumber();
    const startPage = promptNumber("起始页码", detectedStartPage, 1, MAX_PAGE_LIMIT);
    const detectedTotalPage = MAX_PAGE_LIMIT;
    const defaultMaxPages = Math.min(detectedTotalPage - startPage + 1, Math.max(1, Math.ceil(totalLimit / 20) + 2));
    const maxPages = promptNumber("最多翻页数", defaultMaxPages, 1, MAX_PAGE_LIMIT);
    const delaySeconds = promptNumber("每页间隔秒数（建议5秒以上）", DEFAULT_DELAY_SECONDS, 3, 30);

    const sourceKeyword = promptCleanKeyword(getSourceKeyword(document));
    const allCards = [];
    const dedupeKeySet = new Set();
    const pageTextList = [];
    const endPage = Math.min(detectedTotalPage, startPage + maxPages - 1);

    for (let pageNumber = startPage; pageNumber <= endPage; pageNumber += 1) {
      if (state.stopped || allCards.length >= totalLimit) {
        break;
      }
      const pageUrl = buildCleanFactorySearchUrl(sourceKeyword, pageNumber);
      const pageResult = await loadCardsByIframe(pageUrl, panel, pageNumber);

      pageTextList.push(`第${pageNumber}页 ${pageResult.pageTitle}\n${pageResult.pageText}`);
      for (const card of pageResult.cards) {
        const companyName = extractCompanyName(card.text);
        const key = `${companyName}|${card.href || card.text.slice(0, 80)}`;
        if (!companyName || dedupeKeySet.has(key)) {
          continue;
        }
        dedupeKeySet.add(key);
        allCards.push(card);
        if (allCards.length >= totalLimit) {
          break;
        }
      }

      updatePanel(panel, `第 ${pageNumber} 页完成，累计 ${allCards.length} 条候选。`);
      if (pageNumber < endPage && allCards.length < totalLimit) {
        await sleep(delaySeconds * 1000);
      }
    }

    removePreviewIframe();

    if (allCards.length === 0) {
      throw new Error("没有识别到可导入的企业卡片，请确认当前是1688搜索结果页。");
    }

    const options = {
      industry: industry || "美妆个护",
      sourceKeyword,
      totalLimit
    };
    updatePanel(panel, `正在合并导入 ${allCards.length} 条候选卡片...`);
    const data = await postSnapshot(
      buildPayload(
        options,
        allCards,
        pageTextList.join("\n\n").slice(0, 300000),
        buildCleanFactorySearchUrl(sourceKeyword, startPage),
        `${document.title} - 1688批量翻页采集`
      )
    );
    alert(`1688批量翻页导入完成：候选 ${allCards.length} 条，入库 ${data.lead_count || 0} 条，解析 ${data.parsed_count || 0} 条。\n\n说明：批量翻页只读取列表页公开可见字段，不进入详情页，因此联系人和电话通常会显示未公开。需要电话时，请打开详情页后选择模式 1 补采。`);
  }

  (async () => {
    const panel = createPanel();
    try {
      if (!is1688Page()) {
        throw new Error("请先打开1688搜索结果页、店铺页或详情页，再点击收藏栏里的1688采集书签。");
      }
      const mode = prompt(`新版 ${SCRIPT_VERSION}：1=当前页/详情页自动点电话并采集；2=按干净关键词重新生成广东找工厂地址并批量翻页`, "2");
      if (mode === null) {
        throw new Error("用户取消采集");
      }
      if (String(mode).trim() === "2") {
        await importPageBatch(panel);
      } else {
        await importCurrentPage(panel);
      }
      updatePanel(panel, "采集完成。");
    } catch (error) {
      if (String(error && error.message).includes("用户取消采集")) {
        updatePanel(panel, "已取消。");
      } else {
        updatePanel(panel, `失败：${error.message || error}`);
        alert(`1688采集失败：${error.message || error}`);
      }
    } finally {
      window.__leadMining1688Running = false;
      setTimeout(() => {
        removePreviewIframe();
        const panelElement = document.getElementById("lead-mining-1688-panel");
        if (panelElement && panelElement.parentElement) {
          panelElement.parentElement.removeChild(panelElement);
        }
      }, 4500);
    }
  })();
})();

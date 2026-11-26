(function () {
  const tg = window.Telegram ? window.Telegram.WebApp : null;
  if (tg) { tg.ready(); tg.expand(); }

  const CATALOG_PAGE_SIZE = 25;
  const RARITY_TONES = [
    ["контрабанд", "contraband"], ["contraband", "contraband"],
    ["тайное", "covert"], ["covert", "covert"],
    ["засекреч", "classified"], ["classified", "classified"],
    ["экзотичн", "classified"], ["exotic", "classified"],
    ["запрещ", "restricted"], ["restricted", "restricted"],
    ["примечательн", "restricted"], ["remarkable", "restricted"],
    ["армейск", "milspec"], ["mil-spec", "milspec"],
    ["превосходн", "milspec"], ["superior", "milspec"],
    ["промышлен", "industrial"], ["industrial", "industrial"],
    ["высшего класса", "industrial"], ["high grade", "industrial"],
    ["ширпотреб", "consumer"], ["consumer", "consumer"],
    ["базового класса", "consumer"], ["base grade", "consumer"],
    ["экстраординар", "rare"], ["extraordinary", "rare"],
    ["★", "rare"]
  ];

  const state = {
    profile: null,
    tab: "inventory",
    invPage: 0,
    invPages: 1,
    boardPage: 0,
    boardQuery: "",
    boardScope: "all",
    boardPages: 1,
    picked: new Set(),
    wanted: null,
    inventoryItems: [],
    catalog: { source: "board", category: null, weapon: null, query: "", page: 0, pages: 1, wear: null, min: "", max: "", sort: "offers_desc", stattrak: false },
    catalogTrees: {},
    catalogTree: null,
    catalogPages: new Map(),
    counter: { offerId: null, picked: new Set() },
  };

  const $ = (id) => document.getElementById(id);

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[ch]);
  }

  function money(value) {
    return typeof value === "number" && value > 0 ? "$" + value.toFixed(2) : null;
  }

  // инвентарь отдаёт цену числом, каталог — готовой строкой Steam («$1.20»)
  function priceLabel(value) {
    if (typeof value === "number") return money(value);
    const text = String(value == null ? "" : value).trim();
    return text || null;
  }

  function authData() {
    // initData из Telegram — приоритет; иначе кэш в sessionStorage, иначе query
    try { if (tg && tg.initData) { sessionStorage.setItem("initData", tg.initData); return tg.initData; } } catch (e) {}
    let cached = "";
    try { cached = sessionStorage.getItem("initData") || ""; } catch (e) {}
    if (cached) return cached;
    const qs = location.search.slice(1);
    let raw = "";
    if (qs.startsWith("initData=")) raw = qs.slice("initData=".length);
    else {
      const m = qs.match(/[&?]initData=([\s\S]*)$/);
      raw = m ? m[1] : "";
    }
    // значение могли закодировать целиком (initData=auth_date%3D...%26hash%3D...)
    if (raw && !raw.includes("&") && raw.includes("%26")) {
      try { raw = decodeURIComponent(raw); } catch (e) { /* оставляем как есть */ }
    }
    // приложение чистит query после старта: без кэша перезагрузка страницы
    // вне Telegram теряла бы авторизацию и показывала 401
    if (raw) { try { sessionStorage.setItem("initData", raw); } catch (e) {} }
    return raw;
  }

  const API_ERRORS = {
    unauthorized: "Нужна авторизация через Telegram — откройте приложение кнопкой в боте.",
    forbidden: "Недостаточно прав для этого действия.",
    not_found: "Не найдено — возможно, данные уже изменились.",
    bad_request: "Некорректный запрос. Проверьте введённые данные.",
    internal_error: "Ошибка на сервере. Попробуйте чуть позже.",
  };

  async function api(path, options) {
    const opts = options || {};
    const headers = { "X-Telegram-Init-Data": authData() };
    if (opts.body) headers["Content-Type"] = "application/json";

    let response;
    try {
      response = await fetch(path, {
        method: opts.method || "GET",
        headers: headers,
        body: opts.body ? JSON.stringify(opts.body) : undefined,
      });
    } catch (networkError) {
      // fetch бросает TypeError("Failed to fetch") — показываем свой текст
      throw new Error("Не удалось связаться с сервером. Проверьте интернет и попробуйте ещё раз.");
    }

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const code = data.error;
      throw new Error(data.hint || API_ERRORS[code] || (code && !/^[a-z_]+$/.test(code) ? code : "") ||
        (response.status >= 500 ? API_ERRORS.internal_error : "Не удалось выполнить действие (код " + response.status + ")."));
    }
    return data;
  }

  function notice(text, kind, opts) {
    const box = $("notice");
    box.innerHTML = "";
    if (!text) { box.hidden = true; return; }
    box.className = "notice " + (kind || "");
    box.textContent = text;
    box.hidden = false;
    if (kind === "error" && opts && opts.retry) {
      const retryButton = document.createElement("button");
      retryButton.className = "notice-retry";
      retryButton.type = "button";
      retryButton.textContent = "Повторить";
      retryButton.addEventListener("click", () => { notice(""); opts.retry(); });
      box.appendChild(retryButton);
    }
    if (kind !== "error") setTimeout(() => { box.hidden = true; }, 4000);
  }

  function fail(error, retry) {
    const text = error.message;
    notice(text, "error", { retry });
  }

  function state_(container, text) {
    container.innerHTML = '<div class="state">' + esc(text) + "</div>";
  }

  function icon(name) {
    return '<svg class="i" aria-hidden="true"><use href="#i-' + name + '"></use></svg>';
  }

  function empty_(container, iconHtml, text, action) {
    container.innerHTML = '<div class="empty"><div class="empty-icon">' + iconHtml +
      "</div><div>" + esc(text) + "</div>" +
      (action ? '<button class="action" id="empty-action" type="button"></button>' : "") +
      "</div>";
    if (action) {
      $("empty-action").textContent = action.label;
      $("empty-action").addEventListener("click", action.onClick);
    }
  }

  // ---------- тема ----------

  // бренд «Тёмный торговый зал» фиксируем: тему Telegram не маппим в токены,
  // светлая/тёмная схемы приложения собственные и полные
  function themeMap() {
    return [];
  }

  function applyTheme() {
    const root = document.documentElement;
    const params = (tg && tg.themeParams) || {};
    themeMap().forEach((pair) => {
      const value = params[pair[0]];
      if (value) root.style.setProperty(pair[1], value);
    });
    // ?theme=dark|light перекрывает выбор темы — удобно для локального предпросмотра
    const forced = new URLSearchParams(location.search).get("theme");
    // вне Telegram всегда фирменная тёмная тема: не зависим от системной схемы
    const scheme = forced || (tg && tg.colorScheme) || "dark";
    root.setAttribute("data-theme", scheme === "dark" ? "dark" : "light");
  }

  applyTheme();
  if (tg && tg.onEvent) {
    tg.onEvent("themeChanged", applyTheme);
    // Telegram присылает initData позже загрузки скрипта: без этого первый
    // /api/me уходил с пустым заголовком и показывал 401
    tg.onEvent("startup", () => { try { sessionStorage.setItem("initData", tg.initData || ""); } catch (e) {} });
  }

  // ---------- скелетоны ----------

  function skeletonCard() {
    return '<div class="card skeleton-card"><div class="sk sk-thumb"></div>' +
      '<div class="body"><div class="sk sk-line"></div><div class="sk sk-line short"></div>' +
      '<div class="sk sk-line price"></div></div></div>';
  }

  function skeletonCards(container, count) {
    let cards = "";
    for (let index = 0; index < count; index += 1) cards += skeletonCard();
    container.innerHTML = '<div class="grid">' + cards + "</div>";
  }

  function skeletonRows(container, count) {
    let rows = "";
    for (let index = 0; index < count; index += 1) {
      rows += '<div class="row skeleton-row"><div class="sk sk-line short"></div>' +
        '<div class="sk sk-line"></div><div class="sk sk-line"></div></div>';
    }
    container.innerHTML = rows;
  }

  // ---------- редкость ----------

  function rarityTone(rarity) {
    const value = String(rarity || "").toLowerCase();
    if (!value) return "default";
    for (let index = 0; index < RARITY_TONES.length; index += 1) {
      const pair = RARITY_TONES[index];
      if (value.indexOf(pair[0]) >= 0) return pair[1];
    }
    return "default";
  }

  // «AK-47 | Redline (Field-Tested)» -> «AK-47 | Redline»
  function shortSkin(name) {
    return String(name || "")
      .replace(/^(StatTrak™?|Souvenir)\s+/i, "")
      .replace(/\s*\((Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)\s*$/, "");
  }

  function initials(name) {
    const words = String(name || "").split(/[|]/).pop().trim().split(/\s+/).slice(0, 2);
    return words.map((word) => word.charAt(0).toUpperCase()).join("") || "?";
  }

  // ---------- профиль ----------

  function renderProfile() {
    const profile = state.profile;
    if (!profile) return;

    const steam = profile.steam || {};
    $("who-name").textContent = steam.persona || profile.first_name || profile.username || "Игрок";

    const pills = [];
    pills.push('<span class="pill rating">' + icon("star") + ' ' + (profile.rating || 0).toFixed(1) + "</span>");
    pills.push('<span class="pill">' + (profile.trades_count || 0) + " сделок</span>");
    if (profile.username) pills.push('<span class="pill">@' + esc(profile.username) + "</span>");
    if (!steam.linked) pills.push('<span class="pill warn">Steam не привязан</span>');
    $("who-meta").innerHTML = pills.join("");

    // публичный профиль: ссылка, которой можно поделиться, и что увидит контрагент
    if (profile.telegram_id) {
      $("public-profile").hidden = false;
      $("public-profile-link").textContent = "Ссылка: " + location.origin + location.pathname + "#/user/" + profile.telegram_id;
      $("public-profile-stats").textContent =
        "Рейтинг " + (profile.rating || 0).toFixed(2) + " · сделок " + (profile.trades_count || 0);
    }

    if (steam.avatar) {
      const avatar = $("avatar");
      if (avatar.tagName !== "IMG") {
        avatar.outerHTML = '<img class="avatar" id="avatar" src="' + esc(steam.avatar) + '" alt="">';
      }
    }

    $("tab-admin").hidden = !profile.is_admin;

    const rows = [
      ["Telegram", "@" + (profile.username || "—")],
      ["Рейтинг", (profile.rating || 0).toFixed(2)],
      ["Сделок", String(profile.trades_count || 0)],
      ["Steam", steam.linked ? (steam.persona || "привязан") : "не привязан"],
      ["SteamID64", steam.steam_id || "—"],
      ["Trade URL", steam.trade_url || "—"],
      ["Инвентарь", (steam.synced_at ? "обновлён " + steam.synced_at + " UTC" : "ещё не синхронизировался")],
    ];
    $("profile-body").innerHTML = rows
      .map(([key, value]) => '<div class="kv"><span class="k">' + esc(key) + "</span><span>" + esc(value) + "</span></div>")
      .join("") +
      (steam.profile_url ? '<div class="sub"><a href="' + esc(steam.profile_url) + '" target="_blank">Открыть профиль Steam</a></div>' : "");

    if (steam.steam_id && !$("steam-id").value) $("steam-id").value = steam.steam_id || "";
  }

  async function loadMe() {
    state.profile = await api("/api/me");
    renderProfile();
    renderOnboarding();
    return state.profile;
  }

  // онбординг: до привязки Steam показываем подсказку в шапке
  function renderOnboarding() {
    let tip = $("onboarding");
    const steam = state.profile && state.profile.steam;
    if (!tip) {
      tip = document.createElement("div");
      tip.id = "onboarding";
      tip.className = "onboarding";
      const hero = document.querySelector("header.hero");
      if (hero && hero.parentNode) hero.parentNode.insertBefore(tip, hero.nextSibling);
    }
    if (steam && steam.linked) { tip.remove(); return; }
    tip.innerHTML = '<div class="tip">' + icon("link") +
      '<div><b>Добро пожаловать!</b> Привяжите Steam-аккаунт, чтобы загрузить инвентарь и обмениваться скинами.</div>' +
      '<button type="button" id="onboarding-cta">Привязать</button></div>';
    tip.querySelector("#onboarding-cta").addEventListener("click", () => switchTab("profile"));
  }

  // ---------- инвентарь ----------

  function itemCard(item, options) {
    const opts = options || {};
    const price = money(item.price);
    const tone = rarityTone(item.rarity);
    const badges = [];
    if (item.rarity) badges.push('<span class="badge rar">' + esc(item.rarity) + "</span>");
    if (item.exterior) badges.push('<span class="badge">' + esc(item.exterior) + "</span>");
    if (!item.tradable) badges.push('<span class="badge lock">' + icon("lock") + " не торгуется</span>");
    const thumb = item.image
      ? '<img src="' + esc(item.image) + '" alt="" loading="lazy">'
      : '<span class="thumb-stub">' + esc(initials(item.name)) + "</span>";
    const picked = opts.pickable && state.picked.has(item.id);

    return '<article class="card r-' + tone + (picked ? " picked" : "") + '"' +
      (opts.pickable ? ' data-item="' + item.id + '"' : "") + ">" +
      '<div class="thumb">' + thumb + "</div>" +
      '<span class="pick-mark">✓</span>' +
      '<div class="body"><div class="title">' + esc(item.name) + "</div>" +
      '<div class="price ' + (price ? "" : "unknown") + '">' + (price || "цена неизвестна") + "</div>" +
      (badges.length ? '<div class="badges">' + badges.join("") + "</div>" : "") +
      "</div></article>";
  }

  async function loadInventory(page) {
    const list = $("inventory-list");
    skeletonCards(list, 8);

    const data = await api("/api/inventory?page=" + page);
    state.invPage = data.page;
    state.invPages = data.pages;
    state.inventoryItems = data.items;

    $("inventory-stat").innerHTML = "<b>" + data.total + "</b> предметов · торгуемых <b>" +
      data.tradable + "</b>" + (data.value ? " · " + esc(money(data.value)) : "");

    if (!data.items.length) {
      const linked = state.profile && state.profile.steam && state.profile.steam.linked;
      empty_(list, icon("backpack"), linked
        ? "Инвентарь пуст. Синхронизируйте профиль — скины подтянутся из Steam."
        : "Скины появятся здесь после привязки Steam-аккаунта: бот подтянет инвентарь автоматически.",
        linked ? { label: "Синхронизировать", onClick: () => $("sync").click() }
               : { label: "Привязать Steam", onClick: () => switchTab("profile") });
    } else {
      list.innerHTML = '<div class="grid">' + data.items.map((item) => itemCard(item)).join("") + "</div>";
    }

    $("inventory-pager").hidden = data.pages <= 1;
    $("inv-label").textContent = (data.page + 1) + " / " + data.pages;
    $("inv-prev").disabled = data.page === 0;
    $("inv-next").disabled = data.page + 1 >= data.pages;
  }

  $("sync").addEventListener("click", async () => {
    const button = $("sync");
    button.disabled = true;
    button.textContent = "Синхронизирую…";
    try {
      const report = await api("/api/inventory/sync", { method: "POST" });
      notice("Готово: добавлено " + report.created + ", обновлено " + report.updated + ", удалено " + report.removed, "ok");
      await loadMe();
      await loadInventory(0);
      renderCreateItems();
    } catch (error) {
      fail(error);
    } finally {
      button.disabled = false;
      button.innerHTML = icon("refresh") + "<span>Синхронизировать</span>";
    }
  });

  $("inv-prev").addEventListener("click", () => loadInventory(state.invPage - 1).catch((e) => fail(e, () => loadInventory(state.invPage - 1))));
  $("inv-next").addEventListener("click", () => loadInventory(state.invPage + 1).catch((e) => fail(e, () => loadInventory(state.invPage + 1))));

  // ---------- каталог ----------

  function treeUrl() {
    return state.catalog.source === "board" ? "/api/catalog/available/tree" : "/api/catalog/tree";
  }

  async function loadCatalog() {
    $("catalog-source").querySelectorAll("button").forEach((button) => {
      button.classList.toggle("active", button.getAttribute("data-source") === state.catalog.source);
    });
    const cached = state.catalogTrees[state.catalog.source];
    if (!cached) {
      $("catalog-categories").innerHTML =
        '<span class="sk sk-pill"></span><span class="sk sk-pill"></span><span class="sk sk-pill"></span>';
      const tree = await api(treeUrl());
      state.catalogTrees[state.catalog.source] = { categories: tree.categories, total: tree.total };
    }
    state.catalogTree = state.catalogTrees[state.catalog.source].categories;
    state.catalogTreeTotal = state.catalogTrees[state.catalog.source].total;
    $("catalog-stat").innerHTML = state.catalog.source === "board"
      ? "<b>" + state.catalogTreeTotal + "</b> скинов на обмене"
      : "<b>" + state.catalogTreeTotal + "</b> скинов в каталоге";
    renderCatalogChips();
    renderWearChips();
    await loadCatalogItems(0);
  }

  function renderCatalogChips() {
    const categories = state.catalogTree || [];
    $("catalog-categories").innerHTML =
      '<button data-category="" class="' + (state.catalog.category ? "" : "active") + '">Все</button>' +
      categories.map((category) =>
        '<button data-category="' + esc(category.code) + '" class="' +
        (state.catalog.category === category.code ? "active" : "") + '">' +
        esc(category.title) + " · " + category.count + "</button>"
      ).join("");

    const current = categories.find((category) => category.code === state.catalog.category);
    const weapons = current ? current.weapons : [];
    const container = $("catalog-weapons");
    container.hidden = !weapons.length;
    container.innerHTML =
      '<button data-weapon="" class="' + (state.catalog.weapon ? "" : "active") + '">Всё оружие</button>' +
      weapons.map((weapon) =>
        '<button data-weapon="' + esc(weapon.weapon) + '" class="' +
        (state.catalog.weapon === weapon.weapon ? "active" : "") + '">' +
        esc(weapon.weapon) + " · " + weapon.count + "</button>"
      ).join("");
  }

  const WEAR_CHIPS = [
    ["", "Любой износ"],
    ["fn", "FN"],
    ["mw", "MW"],
    ["ft", "FT"],
    ["ww", "WW"],
    ["bs", "BS"]
  ];

  function hasCatalogFilters() {
    const defaultSort = state.catalog.source === "board" ? "offers_desc" : "price_asc";
    return Boolean(
      state.catalog.category || state.catalog.weapon || state.catalog.query ||
      state.catalog.wear || state.catalog.min || state.catalog.max ||
      state.catalog.stattrak || (state.catalog.sort && state.catalog.sort !== defaultSort)
    );
  }

  function renderWearChips() {
    $("catalog-wear").innerHTML = WEAR_CHIPS.map((chip) =>
      '<button data-wear="' + chip[0] + '" class="' +
      ((state.catalog.wear || "") === chip[0] ? "active" : "") + '">' + esc(chip[1]) + "</button>"
    ).join("");
    $("catalog-stattrak").setAttribute("aria-pressed", state.catalog.stattrak ? "true" : "false");
    $("catalog-sort").value = state.catalog.sort;
    const boardOnly = state.catalog.source === "board";
    $("catalog-wear").hidden = boardOnly;
    $("catalog-stattrak").hidden = boardOnly;
    $("catalog-min").closest(".filter-field").hidden = boardOnly;
    $("catalog-max").closest(".filter-field").hidden = boardOnly;
  }

  function catalogQuery(page) {
    const params = new URLSearchParams({ page: String(page), size: String(CATALOG_PAGE_SIZE) });
    if (state.catalog.category) params.set("category", state.catalog.category);
    if (state.catalog.weapon) params.set("weapon", state.catalog.weapon);
    if (state.catalog.query) params.set("q", state.catalog.query);
    if (state.catalog.source === "board") {
      if (state.catalog.sort) params.set("sort", state.catalog.sort);
      return params.toString();
    }
    if (state.catalog.wear) params.set("wear", state.catalog.wear);
    if (state.catalog.min) params.set("min", state.catalog.min);
    if (state.catalog.max) params.set("max", state.catalog.max);
    if (state.catalog.sort && state.catalog.sort !== "price_asc") params.set("sort", state.catalog.sort);
    if (state.catalog.stattrak) params.set("st", "1");
    return params.toString();
  }

  function catalogUrl(params) {
    return (state.catalog.source === "board" ? "/api/catalog/available?" : "/api/catalog/items?") + params;
  }

  async function fetchCatalogPage(page) {
    const params = catalogQuery(page);
    const cached = state.catalogPages.get(params);
    if (cached) return cached;

    const data = await api(catalogUrl(params));
    state.catalogPages.set(params, data);
    return data;
  }

  function prefetchCatalogPage(page) {
    const params = catalogQuery(page);
    if (state.catalogPages.has(params)) return;
    fetchCatalogPage(page).catch(() => {});
  }

  function catalogCard(item) {
    const price = priceLabel(item.price);
    const tone = rarityTone(item.rarity);
    const badges = [];
    if (item.rarity) badges.push('<span class="badge rar">' + esc(item.rarity) + "</span>");
    if (item.offers) {
      badges.push('<span class="badge">' + icon("swap") + " " + item.offers + " " + plural(item.offers, "предложение", "предложения", "предложений") + "</span>");
    }
    const thumb = item.image
      ? '<img src="' + esc(item.image) + '" alt="" loading="lazy">'
      : '<span class="thumb-stub">' + esc(initials(item.name)) + "</span>";

    const actions = state.catalog.source === "board"
      ? '<button class="ghost tiny" data-board-name="' + esc(item.name) + '"><svg class="i" aria-hidden="true"><use href="#i-clipboard"></use></svg> На доске</button>' +
        '<button class="ghost tiny" data-want="' + esc(item.name) + '"><svg class="i" aria-hidden="true"><use href="#i-target"></use></svg> Хочу</button>'
      : '<button class="ghost tiny" data-want="' + esc(item.name) + '"><svg class="i" aria-hidden="true"><use href="#i-target"></use></svg> Хочу это</button>';

    return '<article class="card r-' + tone + '">' +
      '<div class="thumb">' + thumb + "</div>" +
      '<div class="body"><div class="title">' + esc(item.name) + "</div>" +
      '<div class="price ' + (price ? "" : "unknown") + '">' + (price || "цена неизвестна") + "</div>" +
      (badges.length ? '<div class="badges">' + badges.join("") + "</div>" : "") +
      '<div class="actions">' + actions + "</div>" +
      "</div></article>";
  }

  function plural(count, one, few, many) {
    const tail = count % 100;
    if (tail >= 11 && tail <= 14) return many;
    const last = count % 10;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  async function loadCatalogItems(page) {
    const list = $("catalog-list");
    const key = catalogQuery(page);
    const cached = state.catalogPages.get(key);

    if (!cached) skeletonCards(list, 6);
    const data = cached || await fetchCatalogPage(page);

    state.catalog.page = data.page;
    state.catalog.pages = data.pages;
    state.catalog.total = data.total;
    $("catalog-stat").innerHTML = hasCatalogFilters()
      ? "Найдено <b>" + data.total + "</b> из " + (state.catalogTreeTotal || data.total)
      : "<b>" + data.total + "</b> скинов в каталоге";

    if (!data.items.length) {
      empty_(list, icon("search"), "Ничего не нашлось. Сбросьте фильтры или измените запрос.",
        { label: "Сбросить фильтры", onClick: () => { resetCatalogFilters(); $("catalog-search").value = ""; loadCatalog().catch((e) => fail(e, () => loadCatalog())); } });
    } else {
      list.innerHTML = '<div class="grid">' + data.items.map((item) => catalogCard(item)).join("") + "</div>";
    }

    $("catalog-pager").hidden = data.pages <= 1;
    $("catalog-label").textContent = (data.page + 1) + " / " + data.pages;
    $("catalog-prev").disabled = data.page === 0;
    $("catalog-next").disabled = data.page + 1 >= data.pages;

    if (data.page + 1 < data.pages) prefetchCatalogPage(data.page + 1);
  }

  $("catalog-categories").addEventListener("click", (event) => {
    const button = event.target.closest("[data-category]");
    if (!button) return;
    state.catalog.category = button.getAttribute("data-category") || null;
    state.catalog.weapon = null;
    renderCatalogChips();
    loadCatalogItems(0).catch((e) => fail(e, () => loadCatalogItems(0)));
  });

  $("catalog-weapons").addEventListener("click", (event) => {
    const button = event.target.closest("[data-weapon]");
    if (!button) return;
    state.catalog.weapon = button.getAttribute("data-weapon") || null;
    renderCatalogChips();
    loadCatalogItems(0).catch((e) => fail(e, () => loadCatalogItems(0)));
  });

  $("catalog-find").addEventListener("click", () => {
    state.catalog.query = $("catalog-search").value.trim();
    loadCatalogItems(0).catch((e) => fail(e, () => loadCatalogItems(0)));
  });

  $("catalog-source").addEventListener("click", (event) => {
    const button = event.target.closest("[data-source]");
    if (!button) return;
    const source = button.getAttribute("data-source");
    if (source === state.catalog.source) return;
    state.catalog.source = source;
    state.catalog.category = null;
    state.catalog.weapon = null;
    state.catalog.sort = source === "board" ? "offers_desc" : "price_asc";
    state.catalogPages.clear();
    loadCatalog().catch((e) => fail(e, () => loadCatalog()));
  });

  function resetCatalogFilters() {
    state.catalog = {
      source: state.catalog.source, category: null, weapon: null, query: "", page: 0, pages: 1,
      wear: null, min: "", max: "", sort: state.catalog.source === "board" ? "offers_desc" : "price_asc",
      stattrak: false
    };
    state.catalogPages.clear();
    $("catalog-search").value = "";
    $("catalog-min").value = "";
    $("catalog-max").value = "";
    renderCatalogChips();
    renderWearChips();
  }

  $("catalog-reset").addEventListener("click", () => {
    resetCatalogFilters();
    loadCatalogItems(0).catch((e) => fail(e, () => loadCatalogItems(0)));
  });

  $("catalog-wear").addEventListener("click", (event) => {
    const button = event.target.closest("[data-wear]");
    if (!button) return;
    state.catalog.wear = button.getAttribute("data-wear") || null;
    renderWearChips();
    loadCatalogItems(0).catch((e) => fail(e, () => loadCatalogItems(0)));
  });

  $("catalog-stattrak").addEventListener("click", () => {
    state.catalog.stattrak = !state.catalog.stattrak;
    renderWearChips();
    loadCatalogItems(0).catch((e) => fail(e, () => loadCatalogItems(0)));
  });

  $("catalog-sort").addEventListener("change", () => {
    state.catalog.sort = $("catalog-sort").value;
    loadCatalogItems(0).catch((e) => fail(e, () => loadCatalogItems(0)));
  });

  function applyPriceFilter() {
    state.catalog.min = $("catalog-min").value.trim();
    state.catalog.max = $("catalog-max").value.trim();
    loadCatalogItems(0).catch((e) => fail(e, () => loadCatalogItems(0)));
  }

  $("catalog-min").addEventListener("change", applyPriceFilter);
  $("catalog-max").addEventListener("change", applyPriceFilter);

  $("catalog-prev").addEventListener("click", () => loadCatalogItems(state.catalog.page - 1).catch((e) => fail(e, () => loadCatalogItems(state.catalog.page - 1))));
  $("catalog-next").addEventListener("click", () => loadCatalogItems(state.catalog.page + 1).catch((e) => fail(e, () => loadCatalogItems(state.catalog.page + 1))));

  $("catalog-list").addEventListener("click", (event) => {
    const toBoard = event.target.closest("[data-board-name]");
    if (toBoard) {
      const name = toBoard.getAttribute("data-board-name");
      state.boardScope = "all";
      state.boardQuery = name;
      document.querySelectorAll("#board-scope button").forEach((item) => {
        item.classList.toggle("active", item.getAttribute("data-scope") === "all");
      });
      switchTab("board").then(() => {
        $("board-search").value = name;
        loadBoard(0).catch((e) => fail(e, () => loadBoard(0)));
      }).catch(fail);
      return;
    }
    const button = event.target.closest("[data-want]");
    if (!button) return;
    state.wanted = button.getAttribute("data-want");
    $("wanted-input").value = state.wanted;
    notice("Добавлено в «хочу»: " + state.wanted, "ok");
    switchTab("create");
  });

  // ---------- встречное предложение ----------

  async function openCounter(offerId) {
    state.counter = { offerId: Number(offerId), picked: new Set() };
    $("counter-title").textContent = "Предложение по обмену #" + offerId;
    await switchTab("counter");
  }

  async function loadCounter() {
    const container = $("counter-items");
    skeletonCards(container, 6);

    const data = await api("/api/inventory?page=0&size=50");
    const items = data.items.filter((item) => item.tradable);
    if (!items.length) {
      empty_(container, icon("lock"), "Нет торгуемых скинов — синхронизируйте инвентарь.");
      return;
    }
    container.innerHTML = '<div class="grid">' + items.map((item) => itemCard(item, { pickable: true })).join("") + "</div>";
    updateCounterLabel();
  }

  function updateCounterLabel() {
    $("counter-picked").textContent = "Выбрано: " + state.counter.picked.size;
  }

  $("counter-items").addEventListener("click", (event) => {
    const card = event.target.closest("[data-item]");
    if (!card) return;
    const itemId = Number(card.getAttribute("data-item"));
    if (state.counter.picked.has(itemId)) state.counter.picked.delete(itemId);
    else state.counter.picked.add(itemId);
    card.classList.toggle("picked", state.counter.picked.has(itemId));
    updateCounterLabel();
  });

  $("counter-back").addEventListener("click", () => switchTab("board"));

  $("counter-send").addEventListener("click", async () => {
    if (!state.counter.offerId) return;
    if (!state.counter.picked.size) { notice("Выберите хотя бы один свой скин", "error"); return; }

    try {
      const result = await api("/api/offers/" + state.counter.offerId + "/accept", {
        method: "POST",
        body: { item_ids: Array.from(state.counter.picked) },
      });
      if (result.price_warning) notice(result.price_warning, "error");
      notice("Предложение отправлено (#" + result.trade_id + "). Ждём подтверждения автора объявления.", "ok");
      await loadTrades();
      await switchTab("trades");
    } catch (error) {
      fail(error);
    }
  });

  // ---------- доска ----------

  function offeredRow(item, withPrice) {
    const tone = rarityTone(item.rarity);
    const price = withPrice ? priceLabel(item.price) : "";
    return '<div class="sub r-' + tone + '"><span class="badge rar">' + esc(item.rarity || "скин") + "</span> " +
      esc(item.short || item.name) + (price ? " · " + price : "") + "</div>";
  }

  function offerCard(offer, options) {
    const opts = options || {};
    // цену показываем у предмета, только когда их несколько, иначе она дублирует итог
    const items = offer.offered
      .map((item) => offeredRow(item, offer.offered.length > 1))
      .join("");
    const wantedRaw = String(offer.wanted || "").trim();
    const wanted = esc(wantedRaw || "—");
    const comment = String(offer.comment || "").trim();

    const actions = [];
    if (opts.acceptable && !offer.own) {
      actions.push('<button class="action" data-counter="' + offer.id + '">' + icon("swap") + '<span>Предложить обмен</span></button>');
      actions.push('<button class="ghost" data-accept="' + offer.id + '">Забрать без своих скинов</button>');
    }
    if (opts.mine) {
      if (offer.status === "active") actions.push('<button class="ghost" data-cancel="' + offer.id + '">⏸ Снять</button>');
      actions.push('<button class="ghost danger" data-delete="' + offer.id + '">' + icon("trash") + '<span>Удалить</span></button>');
    }

    const matchBadge = offer.match
      ? '<div class="badge match">' + icon("swap") + " ваш " + esc(shortSkin(offer.match)) + "</div>"
      : "";
    const status = offer.status === "active" ? "на доске"
      : offer.status === "in_trade" ? "в сделке"
      : offer.status === "completed" ? "завершено"
      : offer.status === "cancelled" ? "снято"
      : offer.status;

    return '<div class="row"><div class="head"><b>#' + offer.id + " · " + esc(offer.author) + "</b>" +
      '<span class="pill rating">' + icon("star") + " " + (offer.rating || 0).toFixed(1) + "</span></div>" +
      '<div class="split">' +
        '<div class="cell"><div class="label">Отдаёт' +
          (offer.value ? " · " + money(offer.value) : "") + "</div>" +
          (items || '<div class="sub muted">—</div>') + "</div>" +
        '<div class="cell"><div class="label">Хочет</div><div class="sub">' + wanted + "</div>" +
          (comment && comment !== wanted ? '<div class="sub muted">' + esc(comment) + "</div>" : "") +
          "</div>" +
      "</div>" + matchBadge +
      '<div class="sub muted">' + esc(status) + "</div>" +
      (actions.length ? '<div class="actions">' + actions.join("") + "</div>" : "") +
      "</div>";
  }

  async function loadBoard(page) {
    const list = $("board-list");
    skeletonRows(list, 3);

    const suffix = state.boardQuery ? "&q=" + encodeURIComponent(state.boardQuery) : "";
    const scope = state.boardScope === "match" ? "&match=1" : "";
    const data = await api("/api/offers?page=" + page + suffix + scope);
    state.boardPage = data.page;
    state.boardPages = data.pages;
    $("board-stat").innerHTML = state.boardScope === "match"
      ? "Подходят вашему инвентарю: <b>" + data.total + "</b>"
      : state.boardQuery
        ? "Найдено <b>" + data.total + "</b> по запросу «" + esc(state.boardQuery) + "»"
        : "<b>" + data.total + "</b> активных объявлений";

    if (!data.items.length) {
      const boardEmpty = state.boardScope === "match"
        ? ["Пока никто не ищет скины из вашего инвентаря. Синхронизируйте его — совпадения появятся здесь.",
           { label: "Синхронизировать", onClick: () => { switchTab("inventory").then(() => $("sync").click()); } }]
        : state.boardQuery
          ? ["Ничего не нашлось. Попробуйте другое слово или уберите запрос.",
             { label: "Показать все", onClick: () => { $("board-search").value = ""; state.boardQuery = ""; loadBoard(0); } }]
          : ["Доска пуста. Создайте объявление — его увидят все пользователи бота.",
             { label: "Создать", onClick: () => switchTab("create") }];
      empty_(list, icon("clipboard"), boardEmpty[0], boardEmpty[1]);
    } else {
      list.innerHTML = data.items.map((offer) => offerCard(offer, { acceptable: true })).join("");
    }

    $("board-pager").hidden = data.pages <= 1;
    $("board-label").textContent = (data.page + 1) + " / " + data.pages;
    $("board-prev").disabled = data.page === 0;
    $("board-next").disabled = data.page + 1 >= data.pages;
  }

  $("board-scope").addEventListener("click", (event) => {
    const button = event.target.closest("[data-scope]");
    if (!button) return;
    state.boardScope = button.getAttribute("data-scope");
    document.querySelectorAll("#board-scope button").forEach((item) => {
      item.classList.toggle("active", item.getAttribute("data-scope") === state.boardScope);
    });
    loadBoard(0).catch((e) => fail(e, () => loadBoard(0)));
  });

  function runBoardSearch() {
    state.boardQuery = $("board-search").value.trim();
    renderBoardQueryChip();
    loadBoard(0).catch((e) => fail(e, () => loadBoard(0)));
  }

  function renderBoardQueryChip() {
    const stat = $("board-stat");
    if (!stat) return;
    stat.title = state.boardQuery || "";
  }

  $("board-find").addEventListener("click", runBoardSearch);
  $("board-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") runBoardSearch();
  });

  $("board-prev").addEventListener("click", () => loadBoard(state.boardPage - 1).catch((e) => fail(e, () => loadBoard(state.boardPage - 1))));
  $("board-next").addEventListener("click", () => loadBoard(state.boardPage + 1).catch((e) => fail(e, () => loadBoard(state.boardPage + 1))));

  $("board-list").addEventListener("click", async (event) => {
    const counterButton = event.target.closest("[data-counter]");
    if (counterButton) {
      await openCounter(counterButton.getAttribute("data-counter"));
      return;
    }

    const button = event.target.closest("[data-accept]");
    if (!button) return;
    const offerId = button.getAttribute("data-accept");
    if (!confirm("Принять предложение #" + offerId + "?")) return;
    try {
      const result = await api("/api/offers/" + offerId + "/accept", { method: "POST" });
      if (result.price_warning) notice(result.price_warning, "error");
      notice("Сделка #" + result.trade_id + " создана — подтвердите её в «Сделки»", "ok");
      await loadBoard(state.boardPage);
    } catch (error) {
      fail(error);
    }
  });

  // ---------- мои предложения ----------

  async function loadMine() {
    const list = $("mine-list");
    skeletonRows(list, 2);
    const data = await api("/api/my_offers");

    $("mine-stat").innerHTML = "<b>" + data.items.length + "</b> объявлений";
    if (!data.items.length) {
      empty_(list, icon("folder"), "Своих объявлений нет. Создайте первое — его увидят все пользователи бота.",
        { label: "Создать", onClick: () => switchTab("create") });
      return;
    }
    list.innerHTML = data.items.map((offer) => offerCard(offer, { mine: true })).join("");
  }

  $("mine-list").addEventListener("click", async (event) => {
    const cancel = event.target.closest("[data-cancel]");
    const remove = event.target.closest("[data-delete]");
    try {
      if (cancel) {
        await api("/api/offers/" + cancel.getAttribute("data-cancel") + "/cancel", { method: "POST" });
        notice("Объявление снято с доски", "ok");
        await loadMine();
      }
      if (remove) {
        if (!confirm("Удалить объявление безвозвратно?")) return;
        await api("/api/offers/" + remove.getAttribute("data-delete") + "/delete", { method: "POST" });
        notice("Объявление удалено", "ok");
        await loadMine();
      }
    } catch (error) {
      fail(error);
    }
  });

  // ---------- создание ----------

  function renderCreateItems() {
    const container = $("create-items");
    const items = state.inventoryItems.filter((item) => item.tradable);

    if (!items.length) {
      empty_(container, icon("lock"), "Нет торгуемых скинов — синхронизируйте инвентарь.");
      return;
    }

    container.innerHTML = '<div class="grid">' +
      items.map((item) => itemCard(item, { pickable: true })).join("") + "</div>";
    updatePickedLabel();
  }

  function updatePickedLabel() {
    $("create-picked").textContent = "Выбрано: " + state.picked.size;
  }

  $("create-items").addEventListener("click", (event) => {
    const card = event.target.closest("[data-item]");
    if (!card) return;
    const itemId = Number(card.getAttribute("data-item"));
    if (state.picked.has(itemId)) state.picked.delete(itemId);
    else state.picked.add(itemId);
    card.classList.toggle("picked", state.picked.has(itemId));
    updatePickedLabel();
  });

  $("create-clear").addEventListener("click", () => {
    state.picked.clear();
    renderCreateItems();
    $("wanted-results").innerHTML = "";
    $("create-preview").innerHTML = "";
    state.wanted = null;
  });

  $("wanted-search").addEventListener("click", async () => {
    const query = $("wanted-input").value.trim();
    if (query.length < 2) { notice("Напишите хотя бы два символа", "error"); return; }
    try {
      const data = await api("/api/catalog?q=" + encodeURIComponent(query));
      if (!data.items.length) {
        empty_($("wanted-results"), icon("search"), "Ничего не нашлось. Уточните название или оставьте поле пустым.");
        return;
      }
      $("wanted-results").innerHTML = data.items.map((item, index) =>
        '<div class="row"><div class="head"><b>' + esc(item.name) + "</b>" +
        '<span class="pill">' + esc(item.price || "цена неизвестна") + "</span></div>" +
        '<div class="actions"><button class="ghost" data-wanted="' + index + '">Выбрать</button></div></div>'
      ).join("");
      $("wanted-results").setAttribute("data-candidates", JSON.stringify(data.items));
    } catch (error) {
      fail(error);
    }
  });

  $("wanted-results").addEventListener("click", (event) => {
    const button = event.target.closest("[data-wanted]");
    if (!button) return;
    const candidates = JSON.parse($("wanted-results").getAttribute("data-candidates") || "[]");
    const picked = candidates[Number(button.getAttribute("data-wanted"))];
    state.wanted = picked ? picked.name : null;
    notice("Хочу: " + state.wanted, "ok");
  });

  $("create-publish").addEventListener("click", async () => {
    if (!state.picked.size) { notice("Выберите хотя бы один скин", "error"); return; }

    const wantedText = state.wanted || $("wanted-input").value.trim();
    const button = $("create-publish");
    button.disabled = true;
    try {
      const result = await api("/api/offers", {
        method: "POST",
        body: { item_ids: Array.from(state.picked), wanted: wantedText, days: Number($("create-days").value) },
      });
      notice("Объявление #" + result.id + " опубликовано", "ok");
      state.picked.clear();
      state.wanted = null;
      $("wanted-input").value = "";
      $("wanted-results").innerHTML = "";
      await loadInventory(state.invPage);
      renderCreateItems();
      await loadBoard(0);
    } catch (error) {
      fail(error);
    } finally {
      button.disabled = false;
    }
  });

  // ---------- сделки ----------

  function tradeRow(trade) {
    const actions = [];
    trade.actions.forEach((action) => {
      if (action.name === "rate") {
        actions.push('<div class="stars" data-rate="' + trade.id + '">' +
          [1, 2, 3, 4, 5].map((score) => '<button data-score="' + score + '">' + score + "</button>").join("") +
          "</div>");
      } else if (action.name === "dispute") {
        actions.push('<button class="ghost danger" data-dispute="' + trade.id + '">' +
          action.label + "</button>");
      } else {
        actions.push('<button class="ghost" data-trade="' + trade.id + '" data-action="' + action.name + '">' +
          action.label + "</button>");
      }
    });

    const steamLink = trade.steam_url || trade.counterpart_url;
    const link = steamLink
      ? '<div class="actions"><a class="ghost" href="' + esc(steamLink) + '" target="_blank">' + icon("link") + "<span>Steam Trade</span></a></div>"
      : "";
    actions.push('<button class="ghost" data-chat="' + trade.id + '">' + icon("send") + "<span>Чат</span></button>");

    return '<div class="row"><div class="head"><b>#' + trade.id + "</b>" +
      '<span class="pill">' + esc(trade.status_label) + "</span></div>" +
      '<div class="sub">Вы ' + (trade.role === "buyer" ? "покупатель" : "продавец") +
      " · контрагент " + esc(trade.counterpart) + "</div>" +
      '<div class="sub">Подтверждение: ' + (trade.confirmed ? icon("check") : icon("clock")) +
      " · получение: " + (trade.received ? icon("check") : icon("clock")) + "</div>" +
      (trade.protection_note ? '<div class="sub">' + icon("shield") + " " + esc(trade.protection_note) + "</div>" : "") +
      (trade.status === "holding" && trade.finalize_label
        ? '<div class="sub">Сделка станет окончательной ' + esc(trade.finalize_label) + "</div>"
        : "") +
      (trade.dispute_open ? '<div class="sub">' + icon("scale") + ' Открыт спор — ждём решения администратора</div>' : "") +
      (trade.my_items && trade.my_items.length
        ? '<div class="sub">Отдаёте: ' + trade.my_items.map((item) => esc(item.name)).join(", ") + "</div>"
        : "") +
      (trade.their_items && trade.their_items.length
        ? '<div class="sub">Получаете: ' + trade.their_items.map((item) => esc(item.name)).join(", ") + "</div>"
        : "") +
      link +
      (actions.length ? '<div class="actions">' + actions.join("") + "</div>" : "") +
      "</div>";
  }

  async function loadTrades() {
    const list = $("trades-list");
    skeletonRows(list, 2);
    const data = await api("/api/trades");
    if (!data.items.length) {
      empty_(list, icon("swap"), "Сделок пока нет. Найдите скин на доске и предложите обмен.",
        { label: "Открыть доску", onClick: () => switchTab("board") });
      return;
    }

    const incoming = data.items.filter((trade) => trade.direction === "incoming");
    const outgoing = data.items.filter((trade) => trade.direction !== "incoming");

    const blocks = [];
    if (incoming.length) {
      blocks.push('<div class="toolbar"><div class="title">' + icon("inbox") + "<span>Входящие предложения</span></div></div>");
      blocks.push(incoming.map(tradeRow).join(""));
    }
    if (outgoing.length) {
      blocks.push('<div class="toolbar"><div class="title">' + icon("send") + "<span>Мои предложения по обмену</span></div></div>");
      blocks.push(outgoing.map(tradeRow).join(""));
    }
    list.innerHTML = blocks.join("");
  }

  $("trades-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-trade]");
    const star = event.target.closest("[data-score]");
    const dispute = event.target.closest("[data-dispute]");
    const chatBtn = event.target.closest("[data-chat]");
    if (chatBtn) { openChat(Number(chatBtn.getAttribute("data-chat"))); return; }
    try {
      if (dispute) {
        const tradeId = dispute.getAttribute("data-dispute");
        const reason = prompt("Что пошло не так в сделке #" + tradeId + "? Опишите ситуацию для администратора:", "");
        if (reason === null) return;
        const result = await api("/api/trades/" + tradeId + "/dispute", { method: "POST", body: { reason: reason } });
        notice("Спор #" + result.dispute_id + " открыт — администратор уведомлён.", "ok");
        await loadTrades();
        await loadMe();
        return;
      }
      if (button) {
        const tradeId = button.getAttribute("data-trade");
        const action = button.getAttribute("data-action");
        const result = await api("/api/trades/" + tradeId + "/" + action, { method: "POST" });
        if (result.status === "holding") {
          notice("Оба получили скины. Сделка станет окончательной " + result.finalize_label +
            ": до этой даты предметы под Trade Protection и отправитель может отменить трейд.", "ok");
        } else {
          notice("Готово: " + (result.status || action), "ok");
        }
        await loadTrades();
        await loadMe();
      }
      if (star) {
        const tradeId = star.closest("[data-rate]").getAttribute("data-rate");
        const score = Number(star.getAttribute("data-score"));
        const result = await api("/api/trades/" + tradeId + "/rate", { method: "POST", body: { score } });
        notice("Оценка " + score + " поставлена. Рейтинг контрагента: " + result.counterparty_rating.toFixed(2), "ok");
        await loadTrades();
      }
    } catch (error) {
      fail(error);
    }
  });

  // ---------- рейтинг ----------

  // Хотелки «Ищут»: список + добавление
  async function loadWanted() {
    const list = $("wanted-list");
    skeletonRows(list, 3);
    const data = await api("/api/wanted");
    if (!data.items.length) {
      empty_(list, icon("search"), "Хотелок нет. Добавьте скин — уведомим, когда он появится на доске.",
        { label: "Добавить", onClick: () => switchTab("catalog") });
      return;
    }
    list.innerHTML = data.items.map((w) =>
      '<div class="row"><div class="head"><b>' + esc(w.skin_name) + "</b>" +
      '<button class="ghost tiny" data-wanted-del="' + w.id + '">' + icon("trash") + "<span>Убрать</span></button>" +
      "</div></div>"
    ).join("");
  }

  $("wanted-add").addEventListener("click", async () => {
    const input = $("wanted-input");
    const value = input.value.trim();
    if (value.length < 2) { notice("Укажите название скина", "error"); return; }
    try {
      await api("/api/wanted", { method: "POST", body: { skin_name: value } });
      input.value = "";
      notice("Добавлено — уведомим при появлении на доске", "ok");
      await loadWanted();
    } catch (error) {
      fail(error, () => loadWanted());
    }
  });

  $("wanted-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-wanted-del]");
    if (!button) return;
    try {
      await api("/api/wanted/" + button.getAttribute("data-wanted-del"), { method: "DELETE" });
      await loadWanted();
    } catch (error) {
      fail(error, () => loadWanted());
    }
  });

  // Чат сделки: сообщения видят только участники
  let chatTradeId = null;

  async function loadTradeChat() {
    if (!chatTradeId) { switchTab("trades"); return; }
    const box = $("chat-messages");
    skeletonRows(box, 3);
    const data = await api("/api/trades/" + chatTradeId + "/messages");
    $("chat-title").textContent = "Чат сделки #" + chatTradeId;
    renderChat(data.items);
  }

  function renderChat(items) {
    const box = $("chat-messages");
    if (!items.length) {
      empty_(box, icon("send"), "Сообщений нет. Напишите первым — обсудите детали обмена.");
      return;
    }
    box.innerHTML = items.map((m) => {
      const mine = m.sender_id === state.profile.id;
      const who = mine ? "Вы" : (m.sender_username ? "@" + m.sender_username : m.sender_first_name || "Игрок");
      return '<div class="row"><div class="sub"><b>' + esc(who) + " · " + esc(m.created_at) + "</b><br>" + esc(m.body) + "</div></div>";
    }).join("");
    box.scrollTop = box.scrollHeight;
  }

  $("chat-send").addEventListener("click", async () => {
    const input = $("chat-input");
    const text = input.value.trim();
    if (!text || !chatTradeId) return;
    try {
      await api("/api/trades/" + chatTradeId + "/messages", { method: "POST", body: { body: text } });
      input.value = "";
      await loadTradeChat();
    } catch (error) {
      fail(error, () => loadTradeChat());
    }
  });

  $("chat-back").addEventListener("click", () => switchTab("trades"));

  function openChat(tradeId) {
    chatTradeId = tradeId;
    switchTab("trade_chat");
  }

  // Публичный профиль контрагента: рисуем во вкладке «Рейтинг» с шапкой пользователя.
  async function loadPublicUser() {
    const m = location.hash.match(/#\/user\/(\d+)/);
    if (!m) { switchTab("rating"); return; }
    const list = $("rating-list");
    skeletonRows(list, 3);
    const data = await api("/api/users/" + m[1]);
    $("rating-stat").innerHTML =
      "<b>" + esc(data.first_name || data.username || "Игрок") + "</b> · " +
      (data.rating || 0).toFixed(2) + " " + icon("star") +
      " · отзывов " + data.ratings_count + " · сделок " + data.trades_count;

    if (!data.items.length) {
      empty_(list, icon("star"), "Отзывов пока нет — они появляются после завершённых сделок.");
      return;
    }
    list.innerHTML = data.items.map((r) =>
      '<div class="row"><div><b>' + esc(r.author) + "</b> " + icon("star") + " " + r.score +
      '</div><div class="sub">' + esc(r.comment || "") + "</div></div>"
    ).join("");
  }

  async function loadRating() {    const list = $("rating-list");
    skeletonRows(list, 3);
    const data = await api("/api/rating");
    $("rating-stat").innerHTML = "<b>" + data.average.toFixed(2) + "</b> " + icon("star") + " · отзывов " + data.count;

    if (!data.items.length) {
      empty_(list, icon("star"), "Отзывов пока нет — они появляются после завершённых сделок.");
      return;
    }
    list.innerHTML = data.items.map((rating) =>
      '<div class="row"><div class="head"><b>' + rating.score + " " + icon("star") + "</b>" +
      '<span class="pill">' + esc(rating.author) + "</span></div>" +
      '<div class="sub">' + esc(rating.comment || "без комментария") + "</div></div>"
    ).join("");
  }

  // ---------- админка ----------

  async function loadAdmin() {
    const stats = await api("/api/admin/stats");
    $("admin-stats").innerHTML = Object.entries(stats).map(([key, value]) =>
      '<div class="kv"><span class="k">' + esc(key) + "</span><span><b>" + value + "</b></span></div>"
    ).join("");

    const users = await api("/api/admin/users");
    $("admin-users").innerHTML = users.items.map((user) =>
      '<div class="row"><div class="head"><b>' + esc(user.telegram_id) + "</b>" +
      '<span class="pill">' + esc("@" + (user.username || "—")) + "</span></div>" +
      '<div class="sub">' + esc(user.first_name || "—") + " · " + (user.steam ? "Steam " + icon("check") : "Steam " + icon("clock")) +
      " · " + (user.banned ? '<span style="color:var(--danger)">●</span> бан' : '<span style="color:var(--ok)">●</span> активен') + " · " + Number(user.rating).toFixed(1) + " " + icon("star") + " · " +
      user.trades + " сделок</div>" +
      '<div class="actions"><button class="ghost" data-ban="' + user.telegram_id + '" data-unban="' +
      (user.banned ? "1" : "0") + '">' + (user.banned ? "Разбанить" : "Забанить") + "</button></div></div>"
    ).join("");

    const disputes = await api("/api/admin/disputes");
    $("admin-disputes").innerHTML = disputes.items.length
      ? disputes.items.map((dispute) =>
          '<div class="row"><div class="head"><b>#' + dispute.id + "</b>" +
          '<span class="pill">сделка #' + dispute.trade_id + "</span></div>" +
          '<div class="sub">' + esc(dispute.author) + " · " + esc(dispute.reason) + "</div>" +
          '<div class="actions"><button class="ghost" data-resolve="' + dispute.id + '">Решить</button></div></div>'
        ).join("")
      : '<div class="state">Открытых споров нет</div>';
  }

  $("admin-users").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-ban]");
    if (!button) return;
    try {
      await api("/api/admin/ban", {
        method: "POST",
        body: {
          telegram_id: Number(button.getAttribute("data-ban")),
          unban: button.getAttribute("data-unban") === "1",
        },
      });
      notice("Готово", "ok");
      await loadAdmin();
    } catch (error) {
      fail(error);
    }
  });

  $("admin-disputes").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-resolve]");
    if (!button) return;
    const note = prompt("Комментарий к решению", "решение администратора");
    if (note === null) return;
    try {
      await api("/api/admin/disputes/" + button.getAttribute("data-resolve") + "/resolve", {
        method: "POST",
        body: { note },
      });
      notice("Спор закрыт", "ok");
      await loadAdmin();
    } catch (error) {
      fail(error);
    }
  });

  // ---------- профиль: действия ----------

  $("link-steam").addEventListener("click", async () => {
    const steamId = $("steam-id").value.trim();
    if (steamId && !/^\d{17}$/.test(steamId)) {
      notice("SteamID64 — это 17 цифр, например 76561198000000000.", "error");
      return;
    }
    try {
      await api("/api/profile/steam", {
        method: "POST",
        body: { steam_id: steamId, trade_url: $("trade-url").value.trim() },
      });
      notice("Steam привязан", "ok");
      await loadMe();
    } catch (error) {
      fail(error);
    }
  });

  $("refresh-steam").addEventListener("click", async () => {
    try {
      await api("/api/profile/refresh", { method: "POST" });
      notice("Профиль Steam обновлён", "ok");
      await loadMe();
    } catch (error) {
      fail(error);
    }
  });

  // ---------- навигация ----------

  const loaders = {
    inventory: () => loadInventory(state.invPage),
    counter: loadCounter,
    catalog: loadCatalog,
    board: () => loadBoard(state.boardPage),
    create: async () => { await loadInventory(0); renderCreateItems(); },
    mine: loadMine,
    trades: loadTrades,
    trade_chat: loadTradeChat,
    profile: loadMe,
    rating: loadRating,
    admin: loadAdmin,
    public_user: loadPublicUser,
    wanted: loadWanted,
    help: async () => {},
  };

  const PRIMARY_TABS = ["inventory", "catalog", "board", "trades", "profile"];

  function closeMore() {
    const sheet = $("tabs-more");
    if (sheet) sheet.hidden = true;
    const btn = $("tabs-more-btn");
    if (btn) btn.classList.remove("force-open");
  }

  function toggleMore() {
    const sheet = $("tabs-more");
    if (!sheet) return;
    sheet.hidden = !sheet.hidden;
  }

  $("board-cta").addEventListener("click", () => { switchTab("create"); });

  async function switchTab(tab) {
    state.tab = tab;
    document.querySelectorAll("#tabs button").forEach((button) => {
      button.classList.toggle("active", button.getAttribute("data-tab") === tab);
    });
    const moreBtn = $("tabs-more-btn");
    if (moreBtn) moreBtn.classList.toggle("active", !PRIMARY_TABS.includes(tab));
    closeMore();
    document.querySelectorAll("main section").forEach((section) => {
      section.hidden = section.id !== "view-" + tab;
    });
    window.scrollTo(0, 0);
    try {
      const loader = loaders[tab];
      if (loader) await loader();
    } catch (error) {
      fail(error, () => loaders[state.tab] && loaders[state.tab]());
      // чтобы экран не оставался мёртвым — рисуем empty-состояние в списке вкладки
      const lists = {
        inventory: "inventory-list", catalog: "catalog-list", board: "board-list",
        mine: "mine-list", trades: "trades-list",
      };
      const list = lists[tab] && $(lists[tab]);
      if (list) empty_(list, icon("refresh"), "Не удалось загрузить данные. Попробуйте ещё раз.",
        { label: "Повторить", onClick: () => loaders[state.tab] && loaders[state.tab]() });
    }
  }

  $("tabs").addEventListener("click", (event) => {
    const moreBtn = event.target.closest("#tabs-more-btn");
    if (moreBtn) { toggleMore(); return; }
    const button = event.target.closest("button[data-tab]");
    if (button) switchTab(button.getAttribute("data-tab"));
  });

  document.addEventListener("click", (event) => {
    const sheet = $("tabs-more");
    if (!sheet || sheet.hidden) return;
    if (!event.target.closest("#tabs")) closeMore();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMore();
  });

  loadMe()
    .then(() => switchTab("inventory"))
    .catch((error) => {
      fail(error, () => loadMe().then(() => switchTab("inventory")));
      const list = $("inventory-list");
      if (list) empty_(list, icon("refresh"), "Не удалось загрузить данные. Попробуйте ещё раз.",
        { label: "Повторить", onClick: () => loadMe().then(() => switchTab(state.tab)) });
    });

  // live-обновление: активная вкладка перечитывается сама, когда приложение
  // снова на переднем плане и не чаще раза в минуту при долгом просмотре
  let liveTimer = null;
  function scheduleLiveRefresh() {
    clearInterval(liveTimer);
    liveTimer = setInterval(() => {
      if (document.hidden || !loaders[state.tab]) return;
      if (["create", "admin", "help", "rating", "profile"].includes(state.tab)) return;
      loaders[state.tab]().catch(() => { /* тихо: ошибка уже показана загрузчиком */ });
    }, 30000);
  }
  scheduleLiveRefresh();
  document.addEventListener("visibilitychange", () => {
    if (document.hidden || !loaders[state.tab]) return;
    if (["create", "admin", "help", "rating", "profile"].includes(state.tab)) return;
    loaders[state.tab]().catch(() => {});
  });

  // второй вызов на той же странице — обычное обновление вкладки, а не повторный 401:
  // чистим query, чтобы перезагрузка страницы не показывала ошибку авторизации
  if (location.search.includes("initData=")) {
    history.replaceState(null, "", location.pathname);
  }

  // ссылка вида #/user/<id> открывает публичный профиль контрагента
  if (/^#\/user\/\d+/.test(location.hash)) {
    switchTab("rating").then(() => loadPublicUser());
  }
})();

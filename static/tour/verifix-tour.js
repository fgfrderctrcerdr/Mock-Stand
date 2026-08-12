/* ============================================================
   Verifix Onboarding Tour — движок «ведения» ВНУТРИ Verifix.
   Модель A: подсказки-coach-marks поверх реального приложения Verifix +
   постоянная панель-чеклист (как Quick Start в 7shifts).

   Не зависит от фреймворка Verifix (AngularJS) — работает как наложенный
   слой: подсвечивает реальные элементы по CSS-селектору, ведёт по шагам,
   отмечает выполнение (через Verifix API или по DOM), навигирует между
   экранами Verifix.

   Встраивание: добавить <script src="verifix-tour.js"> + <link ...css> в
   оболочку Verifix и вызвать VerifixTour.start(STEPS). См. README.md.

   Публичный API:
     VerifixTour.start(steps, opts)   — запустить/восстановить тур
     VerifixTour.stop()               — скрыть тур
   Формат шага — см. steps.js.
   ============================================================ */

(function (global) {
  'use strict';

  var LS_KEY = 'verifix_tour_progress';
  var state = { steps: [], done: {}, satisfied: {}, opts: {}, activeId: null, pollTimer: null };

  function saveProgress() { try { localStorage.setItem(LS_KEY, JSON.stringify(state.done)); } catch (e) {} }
  function loadProgress() { try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch (e) { return {}; } }

  function currentPath() { return location.pathname + location.search + location.hash; }
  function onRoute(step) {
    // Шаг «привязан» к экрану, если текущий путь содержит step.route.
    return !step.route || currentPath().indexOf(step.route) !== -1;
  }

  function firstUndone() {
    for (var i = 0; i < state.steps.length; i++) {
      if (!state.done[state.steps[i].id]) return state.steps[i];
    }
    return null;
  }

  function markDone(id) {
    if (state.done[id]) return;
    state.done[id] = true;
    saveProgress();
    // Если только что выполненный шаг был активным — двигаем указатель на
    // следующий невыполненный. Раньше это делал advance() рядом с ручной
    // кнопкой «Готово, дальше»; когда её убрали (см. фикс обязательности
    // шагов), про этот переход забыли — activeId зависал на уже
    // выполненном шаге, и он подсвечивался заново при каждом render()
    // (это и была причина «после первого раза снова затемняет поле»).
    if (state.activeId === id) {
      var next = firstUndone();
      state.activeId = next ? next.id : null;
    }
    render();
  }

  // --- Проверка выполнения шага (через step.check: () => bool|Promise<bool>) ---
  //
  // ВАЖНО: сам факт check()===true больше НЕ продвигает шаг автоматически
  // (см. фидбек — раньше после первой же созданной сущности тур сразу
  // толкал к следующему шагу, не давая добавить остальные). Теперь
  // check()===true только помечает "минимум выполнен" (state.satisfied) —
  // это снимает затемнение/рамку и показывает кнопку «Далее», но человек
  // сам решает, когда двигаться дальше. state.done[id] (реальное
  // завершение шага, чек-марка в панели) ставится только по явному клику
  // «Далее» — см. showPopover/markDone.
  function pollActive() {
    clearTimeout(state.pollTimer);
    var step = state.steps.filter(function (s) { return s.id === state.activeId; })[0];
    if (!step || !step.check) return;
    Promise.resolve(step.check(state.opts)).then(function (ok) {
      if (state.satisfied[step.id] !== ok) { state.satisfied[step.id] = ok; render(); return; }
      state.pollTimer = setTimeout(pollActive, step.pollMs || 4000);
    }).catch(function () {
      state.pollTimer = setTimeout(pollActive, step.pollMs || 8000);
    });
  }

  // ============================================================
  // Рендер: панель-чеклист (справа снизу) + попап-подсказка на элементе
  // ============================================================

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  function ensureRoot() {
    var r = document.getElementById('vtour-root');
    if (!r) { r = el('div'); r.id = 'vtour-root'; document.body.appendChild(r); }
    return r;
  }

  // Принудительно открытые дропдауны верхнего меню (см. renderNavGuide)
  // живут ВНЕ #vtour-root (это классы на реальных элементах навигации),
  // поэтому root.innerHTML='' их не убирает — чистим явно на каждый render().
  function clearForcedOpen() {
    var els = document.querySelectorAll('.vtour-force-open');
    for (var i = 0; i < els.length; i++) els[i].classList.remove('vtour-force-open');
  }

  // Кнопка «Далее» (см. renderNextButton) вставляется НАСТОЯЩИМ элементом
  // прямо в страницу (не в #vtour-root — см. пояснение там же), поэтому
  // тоже переживает root.innerHTML='' и требует явной очистки.
  function clearInjectedNextButton() {
    var els = document.querySelectorAll('.vtour-next-inline');
    for (var i = 0; i < els.length; i++) els[i].remove();
  }

  function render() {
    var root = ensureRoot();
    root.innerHTML = '';
    clearForcedOpen();
    clearInjectedNextButton();
    if (state.opts.hidden) return;

    var doneCount = state.steps.filter(function (s) { return state.done[s.id]; }).length;
    var total = state.steps.length;
    var active = state.steps.filter(function (s) { return s.id === state.activeId; })[0] || firstUndone();
    state.activeId = active ? active.id : null;

    // --- Панель-чеклист ---
    var panel = el('div', 'vtour-panel');
    var head = el('div', 'vtour-panel__head',
      '<div class="vtour-panel__title">' + esc(state.opts.title || 'Настройка Verifix') + '</div>' +
      '<button class="vtour-x" title="Свернуть">–</button>');
    panel.appendChild(head);

    var prog = el('div', 'vtour-progress',
      '<div class="vtour-progress__bar"><div class="vtour-progress__fill" style="width:' +
      (total ? Math.round(doneCount / total * 100) : 0) + '%"></div></div>' +
      '<span class="vtour-progress__label">' + doneCount + ' / ' + total + '</span>');
    panel.appendChild(prog);

    var list = el('div', 'vtour-list');
    state.steps.forEach(function (s) {
      var isDone = !!state.done[s.id];
      var isActive = s.id === state.activeId;
      var row = el('button', 'vtour-item' + (isDone ? ' is-done' : '') + (isActive ? ' is-active' : ''));
      row.innerHTML =
        '<span class="vtour-check">' + (isDone ? '✓' : '') + '</span>' +
        '<span class="vtour-item__body"><span class="vtour-item__title">' + esc(s.title) + '</span>' +
        (isActive && s.why ? '<span class="vtour-item__why">' + esc(s.why) + '</span>' : '') + '</span>';
      row.addEventListener('click', function () { goStep(s.id); });
      list.appendChild(row);
    });
    panel.appendChild(list);

    if (doneCount === total && total) {
      panel.appendChild(el('div', 'vtour-done', '🎉 ' + esc(state.opts.doneText || 'Настройка завершена!')));
    }
    root.appendChild(panel);

    head.querySelector('.vtour-x').addEventListener('click', function () {
      panel.classList.toggle('is-min');
    });

    // --- Coach-mark на активном шаге ---
    if (active) renderCoach(active);
  }

  function renderCoach(step) {
    var actionTarget = step.selector ? document.querySelector(step.selector) : null;
    var inputTarget = step.inputSelector ? document.querySelector(step.inputSelector) : null;

    // Если шаг привязан к другому экрану Verifix — ведём через реальную
    // верхнюю навигацию, НО только с нейтральной домашней страницы (там
    // пользователь ничем другим не занят). Если он сам ушёл на какую-то
    // ДРУГУЮ конкретную страницу (например, вернулся посмотреть уже
    // готовые подразделения) — не мешаем: подсказка по невыполненному
    // шагу «наезжала» на то, чем он реально занят в этот момент (см.
    // фидбек №3). Панель-чеклист справа с текстом активного шага
    // остаётся — как добраться, там уже написано, этого достаточно, не
    // навязываем принудительную подсветку меню где угодно, кроме старта.
    if (step.route && !onRoute(step)) {
      if (location.pathname === '/') renderNavGuide(step);
      return;
    }
    if (step.selector && !actionTarget) {
      // На нужном экране, но элемент не найден (селектор уточняется под стенд).
      showPopover(null, step, 'notfound');
      return;
    }

    var primary = inputTarget || actionTarget;

    // Синхронная предпроверка — избегаем «мигания» затемнения на каждой
    // загрузке страницы, когда минимум уже выполнен (see below: без этого
    // затемнение на долю секунды появлялось и сразу гасло при каждом
    // повторном заходе на уже пройденный шаг).
    if (step.check) {
      try {
        var immediate = step.check(state.opts);
        if (immediate && typeof immediate.then !== 'function') state.satisfied[step.id] = !!immediate;
      } catch (e) { /* игнор — обычный поллинг подхватит */ }
    }

    if (step.check && state.satisfied[step.id]) {
      // Минимум выполнен (см. №2/№3 фидбека) — не давим дальше рамкой и
      // затемнением, и НЕ показываем ещё один плавающий попап («ещё один
      // сайдбар», как это назвал пользователь) — вместо него компактная
      // кнопка «Далее» прямо у формы. Человек сам решает, когда закончил
      // добавлять записи; явное продолжение — только по клику на неё.
      renderNextButton(step, actionTarget);
    } else {
      var visuals = primary ? highlight(primary, inputTarget && actionTarget !== inputTarget ? actionTarget : null) : null;
      var pop = showPopover(primary, step, 'ok');

      // По фокусу на подсвеченное поле — убираем и затемнение, и текст
      // подсказки; рамка на поле и стрелка к кнопке остаются как тихий
      // ориентир, куда жать после заполнения.
      if (inputTarget && visuals) {
        var onFocus = function () {
          fadeOut(visuals.dim);
          fadeOut(pop);
          inputTarget.removeEventListener('focus', onFocus);
        };
        inputTarget.addEventListener('focus', onFocus);
      }
    }
    pollActive();
  }

  // Компактная кнопка «Далее» у формы — НЕ всплывающий попап и НЕ
  // position:fixed-элемент (см. фидбек №1/№2: если позиционировать
  // fixed-координатами, посчитанными от вьюпорта, кнопка либо наезжает
  // на форму при её пересчёте, либо оказывается ниже видимой области
  // на длинных формах — а раз она fixed, обычный скролл страницы её не
  // приближает, до неё физически нельзя долистать). Правильное решение —
  // вставить кнопку НАСТОЯЩИМ элементом в поток страницы сразу после
  // формы: тогда она сама съезжает вниз вместе с содержимым и всегда
  // долистываема, как обычная часть страницы.
  function renderNextButton(step, actionTarget) {
    var container = actionTarget
      ? (actionTarget.closest('form') || actionTarget.closest('.entity-form') || actionTarget.parentElement)
      : document.querySelector('.page');
    if (!container) return;

    var wrap = el('div', 'vtour-next-inline');
    wrap.innerHTML =
      '<span class="vtour-next-inline__hint">Минимум выполнен — можно добавить ещё</span>' +
      '<button class="vtour-btn vtour-next-inline__btn">' + esc(step.nextLabel || 'Далее →') + '</button>' +
      '<div class="vtour-inline-warning" hidden></div>';
    container.parentNode.insertBefore(wrap, container.nextSibling);

    var warnEl = wrap.querySelector('.vtour-inline-warning');
    wrap.querySelector('.vtour-next-inline__btn').addEventListener('click', function () {
      Promise.resolve(step.check(state.opts)).then(function (ok) {
        if (ok) {
          markDone(step.id);
        } else {
          state.satisfied[step.id] = false;
          warnEl.textContent = step.emptyWarning ||
            'Список пока пуст — добавьте хотя бы одну запись, иначе следующие шаги не будет к чему привязать.';
          warnEl.hidden = false;
        }
      });
    });
  }

  // Ведёт через реальную верхнюю навигацию: находит пункт меню с нужным
  // href, принудительно раскрывает его дропдаун (класс, не hover — иначе
  // не подсветить скрытый по умолчанию пункт), подсвечивает и вкладку, и
  // сам пункт, стрелкой соединяет одно с другим. Клик — обычная ссылка,
  // настоящий переход браузера, как реальная навигация по Verifix.
  function renderNavGuide(step) {
    var link = document.querySelector('a[href="' + step.route + '"]');
    var tabEl = link ? link.closest('.topnav__item') : null;

    if (link && tabEl) {
      tabEl.classList.add('vtour-force-open');
      var tabLabelEl = tabEl.querySelector('.topnav__label') || tabEl;
      highlight(tabLabelEl, null, true);   // лёгкая рамка на вкладке, без затемнения всего экрана
      highlight(link, null);               // рамка + затемнение на самом пункте меню — это и есть цель клика
      drawArrow(ensureRoot(), tabLabelEl, link);
      showPopover(link, step, 'route');
      try { tabLabelEl.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
    } else {
      // Не нашли пункт меню (например, ссылка ещё не отрендерилась) —
      // прежний фолбэк с явной кнопкой перехода.
      showPopover(null, step, 'route');
    }
  }

  function highlight(target, arrowTo, noDim) {
    var root = ensureRoot();
    var r = target.getBoundingClientRect();

    var ring = el('div', 'vtour-highlight-ring');
    ring.style.top = (r.top - 6) + 'px';
    ring.style.left = (r.left - 6) + 'px';
    ring.style.width = (r.width + 12) + 'px';
    ring.style.height = (r.height + 12) + 'px';
    root.appendChild(ring);

    var dim = null;
    if (!noDim) {
      dim = el('div', 'vtour-highlight-dim');
      dim.style.top = ring.style.top; dim.style.left = ring.style.left;
      dim.style.width = ring.style.width; dim.style.height = ring.style.height;
      root.appendChild(dim);
    }

    if (arrowTo) drawArrow(root, target, arrowTo);

    try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}

    return { dim: dim, ring: ring };
  }

  function fadeOut(node) {
    if (!node) return;
    node.classList.add('is-fading');
    setTimeout(function () { node.remove(); }, 250);
  }

  function drawArrow(root, from, to) {
    var fr = from.getBoundingClientRect();
    var tr = to.getBoundingClientRect();

    // Раньше стрелка шла от центра поля к центру кнопки и просто выгибалась
    // на 30-70px в сторону — этого не хватало, чтобы обойти соседние поля
    // формы между ними (см. фидбек со скетчем). Теперь заходим и выходим
    // строго с ЛЕВОГО края обоих элементов и уводим дугу далеко влево —
    // за пределы самих полей, а не поперёк них.
    var x1 = fr.left, y1 = fr.top + fr.height / 2;
    var x2 = tr.left, y2 = tr.top + tr.height / 2;
    var swing = Math.max(90, Math.min(160, Math.abs(y2 - y1) * 0.7));
    var cx = Math.min(x1, x2) - swing;
    var cy = (y1 + y2) / 2;

    var minX = Math.min(x1, x2, cx) - 20, minY = Math.min(y1, y2, cy) - 20;
    var maxX = Math.max(x1, x2, cx) + 20, maxY = Math.max(y1, y2, cy) + 20;
    var w = maxX - minX, h = maxY - minY;

    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'vtour-arrow');
    svg.style.top = minY + 'px'; svg.style.left = minX + 'px';
    svg.setAttribute('width', w); svg.setAttribute('height', h);
    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M' + (x1 - minX) + ' ' + (y1 - minY) + ' Q ' + (cx - minX) + ' ' + (cy - minY) + ' ' + (x2 - minX) + ' ' + (y2 - minY));
    svg.appendChild(path);
    // Наконечник смотрит вправо-внутрь (в левый край кнопки), по касательной кривой в конце.
    var angle = Math.atan2(y2 - cy, x2 - cx);
    var hx = x2 - minX, hy = y2 - minY;
    var head = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    var a1 = angle + 2.6, a2 = angle - 2.6;
    head.setAttribute('points',
      hx + ',' + hy + ' ' +
      (hx + 9 * Math.cos(a1)) + ',' + (hy + 9 * Math.sin(a1)) + ' ' +
      (hx + 9 * Math.cos(a2)) + ',' + (hy + 9 * Math.sin(a2)));
    head.setAttribute('class', 'vtour-arrow-head');
    svg.appendChild(head);
    root.appendChild(svg);
  }

  function showPopover(target, step, mode) {
    var pop = el('div', 'vtour-pop');

    // Обязательность: шаг с check() продвигается ТОЛЬКО через реальное выполнение
    // (см. pollActive) — ручной кнопки "Готово, дальше" для него быть не должно,
    // иначе тур продвигается по клику, а не по факту действия (это и была
    // причина "перескакивает раньше времени"). Ручная кнопка — только для
    // шагов без check() (если такие появятся).
    var cta;
    if (mode === 'route') {
      // ФИДБЕК: если пункт меню реально найден и подсвечен стрелкой — кнопки
      // быть не должно вообще. Смысл тура — научить работать с настоящим UI,
      // а кнопка-шорткат этому прямо противоречит (в обход реального клика).
      // Кнопка остаётся ТОЛЬКО как честный fallback, когда селектор не нашёлся
      // и показать пользователю нечего.
      cta = target ? '' : '<button class="vtour-btn vtour-open">' + esc(state.opts.openLabel || 'Открыть экран') + '</button>';
    } else if (step.check) {
      cta = '<div class="vtour-waiting">Ждём выполнения на странице…</div>';
    } else {
      cta = '<button class="vtour-btn vtour-next">' + esc(step.nextLabel || (state.opts.nextLabel || 'Готово, дальше')) + '</button>';
    }
    var note =
      mode === 'notfound' ? '<div class="vtour-note">Элемент не найден на экране — селектор уточним под стенд.</div>' : '';

    // Пропустить — только для явно опциональных шагов (step.optional === true).
    // Сейчас это только «Роли» (когда появятся как шаг); всё остальное — либо
    // системно обязательно (подразделения/должности), либо нужно для JTBD
    // (график/локация/сотрудник/отметка/отчёт) — пропуска не даём.
    var skipBtn = step.optional ? '<button class="vtour-btn vtour-btn--ghost vtour-skip">Пропустить</button>' : '';
    var actionsHtml = (skipBtn || cta) ? ('<div class="vtour-pop__actions">' + skipBtn + cta + '</div>') : '';

    pop.innerHTML =
      '<div class="vtour-pop__title">' + esc(step.title) + '</div>' +
      (step.why ? '<div class="vtour-pop__why">' + esc(step.why) + '</div>' : '') +
      note + actionsHtml;
    ensureRoot().appendChild(pop);

    // Позиционирование: НЕ просто «под полем» (перекрывало соседние поля
    // формы, см. фидбек) — пробуем сначала справа от цели, потом слева,
    // и только если по горизонтали не влезает никуда — сверху/снизу с
    // отступом побольше. По центру экрана — только когда нет цели вообще.
    if (target) {
      var r = target.getBoundingClientRect();
      var pr = pop.getBoundingClientRect();
      var margin = 16;
      var top, left;
      if (r.right + margin + pr.width <= window.innerWidth) {
        left = r.right + margin;
        top = Math.min(window.innerHeight - pr.height - 12, Math.max(12, r.top));
      } else if (r.left - margin - pr.width >= 0) {
        left = r.left - margin - pr.width;
        top = Math.min(window.innerHeight - pr.height - 12, Math.max(12, r.top));
      } else {
        left = Math.max(12, Math.min(window.innerWidth - pr.width - 12, r.left));
        top = r.bottom + margin + 24;   // побольше отступ, чтобы не наезжать на следующее поле
        if (top + pr.height > window.innerHeight - 12) top = Math.max(12, r.top - pr.height - margin);
      }
      pop.style.top = top + 'px';
      pop.style.left = left + 'px';
    } else {
      pop.classList.add('vtour-pop--center');
    }

    var openBtn = pop.querySelector('.vtour-open');
    if (openBtn) openBtn.addEventListener('click', function () { location.href = step.route; });
    var nextBtn = pop.querySelector('.vtour-next');
    if (nextBtn) nextBtn.addEventListener('click', function () { markDone(step.id); });
    var skipEl = pop.querySelector('.vtour-skip');
    if (skipEl) skipEl.addEventListener('click', function () { advance(step.id, true); });
    return pop;
  }

  function advance(afterId, skip) {
    if (skip) { /* не отмечаем done, просто переходим к следующему невыполненному */ }
    var next = firstUndone();
    state.activeId = next ? next.id : null;
    render();
  }

  function goStep(id) { state.activeId = id; render(); }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ============================================================
  // Публичный API
  // ============================================================

  var API = {
    start: function (steps, opts) {
      state.steps = steps || [];
      state.opts = opts || {};
      state.done = loadProgress();
      state.satisfied = {};
      var active = firstUndone();
      state.activeId = active ? active.id : null;

      // Интро — один раз, только если прогресса вообще ещё не было
      // (первый визит в эту песочницу). См. opts.intro: { title, text, cta }.
      var seenIntro = false;
      try { seenIntro = !!localStorage.getItem(LS_KEY + '_intro_seen'); } catch (e) {}
      var noProgressYet = Object.keys(state.done).length === 0;

      if (opts && opts.intro && noProgressYet && !seenIntro) {
        renderIntro(opts.intro);
      } else {
        render();
      }
      window.addEventListener('popstate', render);
      window.addEventListener('hashchange', render);
      window.addEventListener('resize', render);
    },
    stop: function () { clearTimeout(state.pollTimer); var r = document.getElementById('vtour-root'); if (r) r.remove(); },
    reset: function () { state.done = {}; state.satisfied = {}; saveProgress(); render(); },
    _state: state,
  };

  function renderIntro(intro) {
    var root = ensureRoot();
    root.innerHTML = '';
    var overlay = el('div', 'vtour-intro-overlay');
    var card = el('div', 'vtour-intro-card');
    card.innerHTML =
      '<div class="vtour-intro-card__title">' + esc(intro.title || 'Добро пожаловать') + '</div>' +
      '<div class="vtour-intro-card__text">' + esc(intro.text || '') + '</div>' +
      '<button class="vtour-btn vtour-intro-start">' + esc(intro.cta || 'Начать') + '</button>';
    overlay.appendChild(card);
    root.appendChild(overlay);
    card.querySelector('.vtour-intro-start').addEventListener('click', function () {
      try { localStorage.setItem(LS_KEY + '_intro_seen', '1'); } catch (e) {}
      render();
    });
  }

  global.VerifixTour = API;
})(window);

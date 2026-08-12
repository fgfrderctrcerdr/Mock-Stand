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
  var state = { steps: [], done: {}, opts: {}, activeId: null, pollTimer: null };

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
    render();
  }

  // --- Проверка выполнения шага (через step.check: () => bool|Promise<bool>) ---
  function pollActive() {
    clearTimeout(state.pollTimer);
    var step = state.steps.filter(function (s) { return s.id === state.activeId; })[0];
    if (!step || !step.check) return;
    Promise.resolve(step.check(state.opts)).then(function (ok) {
      if (ok) markDone(step.id);
      else state.pollTimer = setTimeout(pollActive, step.pollMs || 4000);
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

  function render() {
    var root = ensureRoot();
    root.innerHTML = '';
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

    // Если шаг привязан к другому экрану Verifix — показываем CTA «Открыть экран».
    if (step.route && !onRoute(step)) {
      showPopover(null, step, 'route');
      return;
    }
    if (step.selector && !actionTarget) {
      // На нужном экране, но элемент не найден (селектор уточняется под стенд).
      showPopover(null, step, 'notfound');
      return;
    }

    // Подсвечиваем поле ввода, если оно задано (см. №1 фидбека — раньше
    // подсвечивалась сразу кнопка, что сбивало с толку: сначала нужно
    // заполнить поле, а уже потом жать «Добавить»). Стрелкой показываем
    // путь от поля к кнопке. Если inputSelector не задан — подсвечиваем
    // саму кнопку, как раньше (для шагов без формы, напр. подтверждение).
    var primary = inputTarget || actionTarget;
    if (primary) highlight(primary, inputTarget && actionTarget !== inputTarget ? actionTarget : null, inputTarget);
    showPopover(primary, step, 'ok');
    pollActive();
  }

  function highlight(target, arrowTo, dimRemovalTarget) {
    var root = ensureRoot();
    var r = target.getBoundingClientRect();

    var ring = el('div', 'vtour-highlight-ring');
    ring.style.top = (r.top - 6) + 'px';
    ring.style.left = (r.left - 6) + 'px';
    ring.style.width = (r.width + 12) + 'px';
    ring.style.height = (r.height + 12) + 'px';
    root.appendChild(ring);

    var dim = el('div', 'vtour-highlight-dim');
    dim.style.top = ring.style.top; dim.style.left = ring.style.left;
    dim.style.width = ring.style.width; dim.style.height = ring.style.height;
    root.appendChild(dim);

    if (arrowTo) drawArrow(root, target, arrowTo);

    try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}

    // По фокусу на подсвеченное поле — снимаем затемнение (см. №1), рамка
    // и стрелка остаются, чтобы человек не терял ориентир на кнопку.
    if (dimRemovalTarget) {
      var onFocus = function () {
        dim.classList.add('is-fading');
        setTimeout(function () { dim.remove(); }, 250);
        dimRemovalTarget.removeEventListener('focus', onFocus);
      };
      dimRemovalTarget.addEventListener('focus', onFocus);
    }
  }

  function drawArrow(root, from, to) {
    var fr = from.getBoundingClientRect();
    var tr = to.getBoundingClientRect();
    var x1 = fr.right, y1 = fr.top + fr.height / 2;
    var x2 = tr.left - 8, y2 = tr.top + tr.height / 2;
    // Если кнопка ниже поля (частый случай — поле сверху, кнопка снизу),
    // ведём стрелку от низа поля к верху кнопки, а не по горизонтали.
    if (Math.abs(y2 - y1) > Math.abs(x2 - x1)) {
      x1 = fr.left + fr.width / 2; y1 = fr.bottom;
      x2 = tr.left + tr.width / 2; y2 = tr.top - 8;
    }
    var minX = Math.min(x1, x2) - 20, minY = Math.min(y1, y2) - 20;
    var w = Math.abs(x2 - x1) + 40, h = Math.abs(y2 - y1) + 40;
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'vtour-arrow');
    svg.style.top = minY + 'px'; svg.style.left = minX + 'px';
    svg.setAttribute('width', w); svg.setAttribute('height', h);
    var mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M' + (x1 - minX) + ' ' + (y1 - minY) + ' Q ' + (mx - minX) + ' ' + (my - minY) + ' ' + (x2 - minX) + ' ' + (y2 - minY));
    svg.appendChild(path);
    var angle = Math.atan2(y2 - my, x2 - mx);
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
      cta = '<button class="vtour-btn vtour-open">' + esc(state.opts.openLabel || 'Открыть экран') + '</button>';
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

    pop.innerHTML =
      '<div class="vtour-pop__title">' + esc(step.title) + '</div>' +
      (step.why ? '<div class="vtour-pop__why">' + esc(step.why) + '</div>' : '') +
      note +
      '<div class="vtour-pop__actions">' + skipBtn + cta + '</div>';
    ensureRoot().appendChild(pop);

    // Позиционирование: рядом с целью или по центру.
    if (target) {
      var r = target.getBoundingClientRect();
      pop.style.top = Math.min(window.innerHeight - 220, r.bottom + 12) + 'px';
      pop.style.left = Math.max(12, Math.min(window.innerWidth - 380, r.left)) + 'px';
    } else {
      pop.classList.add('vtour-pop--center');
    }

    var openBtn = pop.querySelector('.vtour-open');
    if (openBtn) openBtn.addEventListener('click', function () { location.href = step.route; });
    var nextBtn = pop.querySelector('.vtour-next');
    if (nextBtn) nextBtn.addEventListener('click', function () { markDone(step.id); advance(step.id); });
    var skipEl = pop.querySelector('.vtour-skip');
    if (skipEl) skipEl.addEventListener('click', function () { advance(step.id, true); });
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
    reset: function () { state.done = {}; saveProgress(); render(); },
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

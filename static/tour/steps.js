/* ============================================================
   Шаги тура для Mock-Stand.

   Отличие от исходного static/tour черновика (verifix_tour/steps.js
   в основном проекте): здесь селекторы РЕАЛЬНЫЕ, не черновые — потому
   что страницы наши собственные (Mock-Stand), не настоящий Verifix.
   Как только появится доступ к настоящему тестовому стенду Verifix,
   этот файл послужит образцом — меняются только selector/route на
   актуальные из боевого приложения, сам движок (verifix-tour.js)
   не трогается.

   check() детектит выполнение через содержимое таблицы-списка на
   странице (у нас все datatable-строки помечены [data-row-id],
   так же, как в оригинальном черновике gridHasRows()) — единый
   подход что тут, что там.
   ============================================================ */

function gridHasRows() {
  return document.querySelectorAll('[data-row-id]').length > 0;
}

function companyProfileSet() {
  return !!document.querySelector('[data-company-set]');
}

function st(key, fallback) {
  return (typeof window !== 'undefined' && window.VERIFIX_I18N && window.VERIFIX_I18N[key]) || fallback;
}

var VERIFIX_TOUR_STEPS = [
  {
    id: 'company',
    title: st('step.company.title', 'Расскажите о компании'),
    why: st('step.company.why', 'Название, сфера деятельности и ваша роль — это подберёт типовые подразделения и должности под вас.'),
    route: '/',
    inputSelector: 'input[name="company_name"]',
    selector: '[data-tour="add"]',
    check: companyProfileSet,
    autoAdvance: true,   // компания одна, не список — "добавить ещё" здесь не имеет смысла, сразу дальше
    emptyWarning: st('step.company.emptyWarning', 'Заполните название компании, сферу деятельности и свою роль — без этого нельзя продолжить.'),
  },
  {
    id: 'locations',
    title: st('step.locations.title', 'Добавьте локацию'),
    why: st('step.locations.why', 'Место, где сотрудник отмечает приход/уход.'),
    route: '/vhr/htt/location_list',
    inputSelector: '#locName',
    selector: '[data-tour="add"]',
    emptyWarning: st('step.locations.emptyWarning', 'Локация — это место, где сотрудник отмечает приход/уход. Без неё физически негде будет отметиться.'),
    check: gridHasRows,
  },
  {
    id: 'divisions',
    title: st('step.divisions.title', 'Создайте подразделения'),
    why: st('step.divisions.why', 'Оргструктура компании. К подразделениям привязываются сотрудники.'),
    route: '/vhr/hrm/division_list',
    // БАГ: 'input[name="name"]' совпадал ещё и со скрытыми input чипов
    // типовых подразделений (те же name="name", рендерятся раньше в DOM) —
    // querySelector брал ПЕРВЫЙ, то есть скрытый нулевого размера элемент.
    // Отсюда затемнение почти на весь экран, невидимая рамка на реальном
    // поле, стрелка от (0,0) через весь экран, и фокус, который никогда
    // не срабатывал (вешался на скрытый инпут). Используем точный #id.
    inputSelector: '#divName',
    selector: '[data-tour="add"]',
    emptyWarning: st('step.divisions.emptyWarning', 'Подразделения — это структура компании (цех, зал, офис). Без хотя бы одного не к чему будет привязать сотрудников на следующих шагах.'),
    check: gridHasRows,
  },
  {
    id: 'positions',
    title: st('step.positions.title', 'Заведите должности'),
    why: st('step.positions.why', 'Должность определяет, кем работает сотрудник.'),
    route: '/vhr/hrm/job_list',
    inputSelector: '#jobName',   // тот же баг, что у divisions — см. комментарий выше
    selector: '[data-tour="add"]',
    emptyWarning: st('step.positions.emptyWarning', 'Должность — это то, кем работает сотрудник (например, «Официант»). Без неё не получится завести сотрудника.'),
    check: gridHasRows,
  },
  {
    id: 'schedules',
    title: st('step.schedules.title', 'Создайте график работы'),
    why: st('step.schedules.why', 'Правила рабочего времени, которые назначаются сотрудникам.'),
    route: '/vhr/htt/schedule_list',
    inputSelector: '#schName',
    selector: '[data-tour="add"]',
    emptyWarning: st('step.schedules.emptyWarning', 'График определяет, когда сотрудник должен быть на работе. Без него система не поймёт, что считать опозданием или переработкой.'),
    check: gridHasRows,
  },
  {
    id: 'employees',
    title: st('step.employees.title', 'Добавьте сотрудника'),
    why: st('step.employees.why', 'Свяжите подразделение, должность и график в одном сотруднике — локацию прикрепим отдельным шагом дальше.'),
    route: '/vhr/href/employee',
    inputSelector: '#empFullName',
    selector: '[data-tour="add"]',
    // По фидбеку: employees→attach_employee→attach_division — единая
    // демонстрация трёх связанных действий, пауза с "Минимум выполнен"
    // не нужна ПОСРЕДИ неё — только в самом конце цепочки (см.
    // attach_division ниже, у него autoAdvance нет специально).
    autoAdvance: true,
    emptyWarning: st('step.employees.emptyWarning', 'Сотрудник — это тот, кто и будет отмечаться и получать зарплату. Без него оставшиеся шаги (приглашение, отметка, отчёт) не имеют смысла.'),
    check: gridHasRows,
  },
  {
    id: 'attach_employee',
    title: st('step.attach_employee.title', 'Прикрепите сотрудника к локации'),
    why: st('step.attach_employee.why', 'Перетащите КОНКРЕТНОГО сотрудника (аватар внутри карточки подразделения выше) на круг локации — прикрепится только он. Один человек может быть прикреплён сразу к нескольким локациям.'),
    route: null,   // панель справа есть на любой странице — не привязываем к конкретному экрану
    inputSelector: '.ovp__avatar-mini[draggable="true"]',
    selector: '.ovp__location-circle',
    autoAdvance: true,   // сразу продолжаем на attach_division, без промежуточной кнопки "Далее"
    emptyWarning: st('step.attach_employee.emptyWarning', 'Пока ни один сотрудник не прикреплён ни к одной локации — без этого не с чем будет считать отчёт по конкретной точке.'),
    check: function () { return !!document.querySelector('[data-individual-location-attach]'); },
  },
  {
    id: 'attach_division',
    title: st('step.attach_division.title', 'Прикрепите ВСЁ подразделение к локации'),
    why: st('step.attach_division.why', 'Перетащите тёмную ШАПКУ карточки подразделения (не отдельного сотрудника) на круг локации — прикрепятся СРАЗУ ВСЕ сотрудники этого подразделения (можно и через корневой узел компании — тащить всю компанию целиком).'),
    route: null,
    inputSelector: '.ovp__division-head[draggable="true"]',
    selector: '.ovp__location-circle',
    // autoAdvance намеренно НЕТ — это конец цепочки из трёх шагов, здесь
    // и должна появиться пауза "Минимум выполнен" + кнопка "Далее".
    emptyWarning: st('step.attach_division.emptyWarning', 'Это отдельное действие от прикрепления одного сотрудника — попробуйте перетащить именно шапку карточки подразделения, целиком.'),
    // ВТОРОЕ уточнение переигрывает первое: не хард-блок (нельзя перейти
    // вообще), а мягкое подтверждение именно в момент перехода дальше —
    // если сейчас есть хоть один непрёкреплённый сотрудник компании,
    // спросить явно, а не запрещать молча. check() больше не требует
    // отсутствия has_unattached_employees — только сам факт, что
    // прикрепление подразделения вообще происходило хоть раз.
    check: function () { return !!document.querySelector('[data-division-location-attach]'); },
    confirmBeforeAdvance: function () {
      return document.querySelector('[data-has-unattached-employees]')
        ? st('step.attach_division.confirm', 'Не всем сотрудникам прикреплена локация. Это значит, что вы не сможете на 100% быть уверены в том, что данные сотрудники сделали свою отметку на рабочем месте. Уверены, что хотите продолжить?')
        : null;
    },
  },
  {
    id: 'invite',
    title: st('step.invite.title', 'Пригласите сотрудника в приложение'),
    why: st('step.invite.why', 'Как в реальном Verifix: телефон + инвайт. Без этого нет способа сотруднику отметиться.'),
    route: '/vhr/admin/users',
    // Уточнение: телефон теперь ОБЯЗАТЕЛЕН уже при создании сотрудника —
    // к моменту этого шага он всегда уже заполнен, подсвечивать поле
    // ввода больше не имеет смысла (нечего печатать). Подсвечиваем саму
    // кнопку «Пригласить» — единственное реальное действие, которое
    // нужно.
    selector: '[data-tour="add"]',
    // "После приглашения первого пользователя не должно быть
    // подсвечивания" — раз человек уже понял механику на первом, не
    // навязываем то же самое на каждом следующем. check() всё равно
    // продолжает требовать ВСЕХ приглашённых (autoAdvance сработает,
    // только когда действительно все) — просто без визуальной подсказки
    // после первого раза.
    suppressHighlightIf: function () { return !!document.querySelector('[data-has-any-invited]'); },
    // Уточнение: раньше хватало ОДНОГО приглашённого — теперь требуются
    // ВСЕ сотрудники компании (маркер has_uninvited_employees в main.py).
    // autoAdvance — как только приглашены все, сразу ведём дальше (гид
    // на Посещения → Отметки), без паузы "Далее" здесь.
    autoAdvance: true,
    emptyWarning: st('step.invite.emptyWarning', 'Не все сотрудники приглашены — без приглашения у них не будет доступа к приложению, значит, физически нечем будет сделать отметку.'),
    check: function () { return !document.querySelector('[data-has-uninvited-employees]'); },
  },
  {
    id: 'attendance',
    title: st('step.attendance.title', 'Посмотрите отметки посещений'),
    why: st('step.attendance.why', 'Здесь видны отметки прихода/ухода добавленных сотрудников. Если никто ещё не отмечался — список пустой, это нормально: шаг просто показывает, куда смотреть, действие не обязательно.'),
    route: '/vhr/htt/attendance_mark',
    // По уточнению: пассивный шаг — просто зайти и посмотреть, без
    // обязательного создания отметки (раньше требовал gridHasRows).
    // check() всегда true — как только пользователь на нужной странице
    // (route проверяется раньше в движке), считаем выполненным.
    check: function () { return true; },
    doneHint: st('step.attendance.doneHint', 'Здесь видны отметки прихода/ухода сотрудников — список может быть пустым, если никто ещё не отмечался. Когда посмотрели — жмите «Далее».'),
  },
  {
    id: 'report',
    title: st('step.report.title', 'Посмотрите отчёт по посещениям'),
    why: st('step.report.why', 'Отчёт по отработанным часам — в формате как в реальном Verifix. Если отметок ещё не было, отчёт будет пустым, это тоже нормально.'),
    route: '/vhr/htt/timesheet_report',
    check: function () { return true; },
    doneHint: st('step.report.doneHint', 'Отчёт по отработанным часам — как в реальном Verifix. Пусто, если ещё не было отметок — это нормально.'),
  },
];

if (typeof module !== 'undefined') module.exports = { VERIFIX_TOUR_STEPS: VERIFIX_TOUR_STEPS };

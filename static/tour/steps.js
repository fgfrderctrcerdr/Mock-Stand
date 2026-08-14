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

var VERIFIX_TOUR_STEPS = [
  {
    id: 'company',
    title: 'Расскажите о компании',
    why: 'Название, сфера деятельности и ваша роль — это подберёт типовые подразделения и должности под вас.',
    route: '/',
    inputSelector: 'input[name="company_name"]',
    selector: '[data-tour="add"]',
    check: companyProfileSet,
    autoAdvance: true,   // компания одна, не список — "добавить ещё" здесь не имеет смысла, сразу дальше
    emptyWarning: 'Заполните название компании, сферу деятельности и свою роль — без этого нельзя продолжить.',
  },
  {
    id: 'locations',
    title: 'Добавьте локацию',
    why: 'Место, где сотрудник отмечает приход/уход.',
    route: '/vhr/htt/location_list',
    inputSelector: '#locName',
    selector: '[data-tour="add"]',
    emptyWarning: 'Локация — это место, где сотрудник отмечает приход/уход. Без неё физически негде будет отметиться.',
    check: gridHasRows,
  },
  {
    id: 'divisions',
    title: 'Создайте подразделения',
    why: 'Оргструктура компании. К подразделениям привязываются сотрудники.',
    route: '/vhr/hrm/division_list',
    // БАГ: 'input[name="name"]' совпадал ещё и со скрытыми input чипов
    // типовых подразделений (те же name="name", рендерятся раньше в DOM) —
    // querySelector брал ПЕРВЫЙ, то есть скрытый нулевого размера элемент.
    // Отсюда затемнение почти на весь экран, невидимая рамка на реальном
    // поле, стрелка от (0,0) через весь экран, и фокус, который никогда
    // не срабатывал (вешался на скрытый инпут). Используем точный #id.
    inputSelector: '#divName',
    selector: '[data-tour="add"]',
    emptyWarning: 'Подразделения — это структура компании (цех, зал, офис). Без хотя бы одного не к чему будет привязать сотрудников на следующих шагах.',
    check: gridHasRows,
  },
  {
    id: 'positions',
    title: 'Заведите должности',
    why: 'Должность определяет, кем работает сотрудник.',
    route: '/vhr/hrm/job_list',
    inputSelector: '#jobName',   // тот же баг, что у divisions — см. комментарий выше
    selector: '[data-tour="add"]',
    emptyWarning: 'Должность — это то, кем работает сотрудник (например, «Официант»). Без неё не получится завести сотрудника.',
    check: gridHasRows,
  },
  {
    id: 'schedules',
    title: 'Создайте график работы',
    why: 'Правила рабочего времени, которые назначаются сотрудникам.',
    route: '/vhr/htt/schedule_list',
    inputSelector: '#schName',
    selector: '[data-tour="add"]',
    emptyWarning: 'График определяет, когда сотрудник должен быть на работе. Без него система не поймёт, что считать опозданием или переработкой.',
    check: gridHasRows,
  },
  {
    id: 'employees',
    title: 'Добавьте сотрудника',
    why: 'Свяжите подразделение, должность и график в одном сотруднике — локацию прикрепим отдельным шагом дальше.',
    route: '/vhr/href/employee',
    inputSelector: '#empFullName',
    selector: '[data-tour="add"]',
    // По фидбеку: employees→attach_employee→attach_division — единая
    // демонстрация трёх связанных действий, пауза с "Минимум выполнен"
    // не нужна ПОСРЕДИ неё — только в самом конце цепочки (см.
    // attach_division ниже, у него autoAdvance нет специально).
    autoAdvance: true,
    emptyWarning: 'Сотрудник — это тот, кто и будет отмечаться и получать зарплату. Без него оставшиеся шаги (приглашение, отметка, отчёт) не имеют смысла.',
    check: gridHasRows,
  },
  {
    id: 'attach_employee',
    title: 'Прикрепите сотрудника к локации',
    why: 'Перетащите КОНКРЕТНОГО сотрудника (аватар внутри карточки подразделения выше) на круг локации — прикрепится только он. Один человек может быть прикреплён сразу к нескольким локациям.',
    route: null,   // панель справа есть на любой странице — не привязываем к конкретному экрану
    inputSelector: '.ovp__avatar-mini[draggable="true"]',
    selector: '.ovp__location-circle',
    autoAdvance: true,   // сразу продолжаем на attach_division, без промежуточной кнопки "Далее"
    emptyWarning: 'Пока ни один сотрудник не прикреплён ни к одной локации — без этого не с чем будет считать отчёт по конкретной точке.',
    check: function () { return !!document.querySelector('[data-individual-location-attach]'); },
  },
  {
    id: 'attach_division',
    title: 'Прикрепите ВСЁ подразделение к локации',
    why: 'Другое действие, не то же самое: перетащите тёмную ШАПКУ карточки подразделения (не отдельного сотрудника) на круг локации — прикрепятся СРАЗУ ВСЕ сотрудники этого подразделения, а не по одному.',
    route: null,
    inputSelector: '.ovp__division-head[draggable="true"]',
    selector: '.ovp__location-circle',
    // autoAdvance намеренно НЕТ — это конец цепочки из трёх шагов, здесь
    // и должна появиться пауза "Минимум выполнен" + кнопка "Далее".
    emptyWarning: 'Это отдельное действие от прикрепления одного сотрудника — попробуйте перетащить именно шапку карточки подразделения, целиком.',
    check: function () { return !!document.querySelector('[data-division-location-attach]'); },
  },
  {
    id: 'invite',
    title: 'Пригласите сотрудника в приложение',
    why: 'Как в реальном Verifix: телефон + инвайт. Без этого нет способа сотруднику отметиться.',
    route: '/vhr/admin/users',
    inputSelector: 'input[name="phone"]',
    selector: '[data-tour="add"]',
    emptyWarning: 'Без приглашения у сотрудника не будет доступа к приложению — значит, физически нечем будет сделать отметку.',
    check: function () { return document.querySelectorAll('[data-invite-active="1"]').length > 0; },
  },
  {
    id: 'attendance',
    title: 'Сотрудник отмечает приход',
    why: 'В реальном Verifix это делает сотрудник в мобильном приложении Verifix ID. Здесь — эмулируем.',
    route: '/vhr/htt/attendance_mark',
    selector: '[data-tour="add"]',
    emptyWarning: 'Пока нет ни одной отметки, отчёт по часам будет пустым — в нём просто не из чего считать часы.',
    check: gridHasRows,
  },
  {
    id: 'report',
    title: 'Посмотрите отчёт по часам',
    why: 'Вот она — ценность системы для клиента, не просто заведённая структура.',
    route: '/vhr/htt/timesheet_report',
    selector: null,   // это финальный шаг — просвещаем, не просим действия на элементе
    emptyWarning: 'Отчёт пока пуст — вернитесь на шаг «Отметки» и отметьте хотя бы один приход/уход, тогда здесь появятся часы.',
    check: gridHasRows,
  },
];

if (typeof module !== 'undefined') module.exports = { VERIFIX_TOUR_STEPS: VERIFIX_TOUR_STEPS };

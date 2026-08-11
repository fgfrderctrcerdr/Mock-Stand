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

var VERIFIX_TOUR_STEPS = [
  {
    id: 'divisions',
    title: 'Создайте подразделения',
    why: 'Оргструктура компании. К подразделениям привязываются сотрудники.',
    route: '/vhr/hrm/division_list',
    selector: '[data-tour="add"]',
    check: gridHasRows,
  },
  {
    id: 'positions',
    title: 'Заведите должности',
    why: 'Должность определяет, кем работает сотрудник.',
    route: '/vhr/hrm/job_list',
    selector: '[data-tour="add"]',
    check: gridHasRows,
  },
  {
    id: 'schedules',
    title: 'Создайте график работы',
    why: 'Правила рабочего времени, которые назначаются сотрудникам.',
    route: '/vhr/htt/schedule_list',
    selector: '[data-tour="add"]',
    check: gridHasRows,
  },
  {
    id: 'locations',
    title: 'Добавьте локацию',
    why: 'Место, где сотрудник отмечает приход/уход.',
    route: '/vhr/htt/location_list',
    selector: '[data-tour="add"]',
    check: gridHasRows,
  },
  {
    id: 'employees',
    title: 'Добавьте сотрудника',
    why: 'Свяжите подразделение, должность, график и локацию в одном сотруднике.',
    route: '/vhr/href/employee',
    selector: '[data-tour="add"]',
    check: gridHasRows,
  },
  {
    id: 'invite',
    title: 'Пригласите сотрудника в приложение',
    why: 'Как в реальном Verifix: телефон + инвайт. Без этого нет способа сотруднику отметиться.',
    route: '/vhr/admin/users',
    selector: '[data-tour="add"]',
    check: function () { return document.querySelectorAll('[data-invite-active="1"]').length > 0; },
  },
  {
    id: 'attendance',
    title: 'JTBD №1: сотрудник отмечает приход',
    why: 'В реальном Verifix это делает сотрудник в мобильном приложении Verifix ID. Здесь — эмулируем.',
    route: '/vhr/htt/attendance_mark',
    selector: '[data-tour="add"]',
    check: gridHasRows,
  },
  {
    id: 'report',
    title: 'JTBD №2: посмотрите отчёт по часам',
    why: 'Вот она — ценность системы для клиента, не просто заведённая структура.',
    route: '/vhr/htt/timesheet_report',
    selector: null,   // это финальный шаг — просвещаем, не просим действия на элементе
    check: gridHasRows,
  },
];

if (typeof module !== 'undefined') module.exports = { VERIFIX_TOUR_STEPS: VERIFIX_TOUR_STEPS };

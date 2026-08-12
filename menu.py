"""
Верхняя навигация — по РЕАЛЬНЫМ скриншотам дропдаунов (не по прежним
догадкам). Верхний уровень теперь: Кадры, Посещения, Управление сменами,
Зарплата, Отчётность, Настройки (6 вкладок — в предыдущей версии были ещё
Эффективность/Развитие/Рекрутинг из более смутного скрина; в этих двух
чётких скринах их нет, доверяем более чёткому источнику).

Каждый раздел — список "columns" (может быть 1 колонка без заголовка,
как «Посещения», или несколько с заголовками, как «Кадры»: Главное /
Организация / Дашборд). Это отражает реальную вёрстку дропдауна Кадры.
"""

MENU = [
    {
        "key": "kadry",
        "label": "Кадры",
        "columns": [
            {
                "title": "Главное",
                "links": [
                    ("/vhr/href/employee", "Сотрудники", True),
                ],
            },
            {
                "title": "Организация",
                "links": [
                    ("/vhr/hrm/division_list", "Подразделения", True),
                    ("/vhr/hrm/retail_points", "Торговые точки", False),
                    ("/vhr/hrm/job_list", "Должности", True),
                ],
            },
            {
                "title": "Дашборд",
                "links": [
                    ("/vhr/hrm/division_stats", "Статистика работы подразделений", False),
                    ("/vhr/hrm/report_queue", "Очередь отчётов", False),
                    ("/vhr/hrm/year_summary", "Итоги года", False),
                ],
            },
        ],
    },
    {
        "key": "poseshcheniya",
        "label": "Посещения",
        "columns": [
            {
                "title": None,
                "links": [
                    ("/vhr/htt/schedule_list", "Графики работы", True),
                    ("/vhr/htt/absence_requests", "Запросы на отсутствие", False),
                    ("/vhr/htt/schedule_change_requests", "Запросы на изменение графика", False),
                    ("/vhr/htt/location_requests", "Запросы на локацию", False),
                    ("/vhr/htt/overtime_requests", "Запросы на сверхурочные", False),
                    ("/vhr/htt/mark_requests", "Запросы на отметки", False),
                    ("/vhr/htt/overtime", "Сверхурочные", False),
                    ("/vhr/htt/location_list", "Локации", True),
                    ("/vhr/htt/devices", "Устройства", False),
                    ("/vhr/htt/attendance_mark", "Отметки", True),
                    ("/vhr/htt/individual_schedules", "Индивидуальные графики", False),
                    ("/vhr/htt/timetables", "Расписания", False),
                    ("/vhr/htt/timetable_change_requests", "Запросы на изменение расписания", False),
                ],
            },
        ],
    },
    {
        "key": "smeny",
        "label": "Управление сменами",
        "columns": [
            {
                "title": None,
                "links": [
                    ("/vhr/hsm/shift_templates", "Шаблоны смен", False),
                    ("/vhr/hsm/shift_assignment", "Назначение смен", False),
                ],
            },
        ],
    },
    {
        "key": "zarplata",
        "label": "Зарплата",
        "columns": [
            {
                "title": None,
                "links": [
                    ("/vhr/hpr/charges", "Начисления", False),
                    ("/vhr/hpr/statements", "Ведомости", False),
                    ("/vhr/hpr/payments", "Выплаты", False),
                ],
            },
        ],
    },
    {
        "key": "otchetnost",
        "label": "Отчётность",
        "columns": [
            {
                "title": None,
                "links": [
                    ("/vhr/htt/timesheet_report", "Отчёт по часам", True),
                    ("/vhr/hpr/payroll_report", "Отчёт по зарплате", False),
                ],
            },
        ],
    },
    {
        "key": "nastroyki",
        "label": "Настройки",
        "columns": [
            {
                "title": "Администрирование",
                "links": [
                    ("/vhr/admin/users", "Пользователи", True),
                    ("/vhr/admin/roles", "Роли", False),
                ],
            },
            {
                "title": "Справочники",
                "links": [
                    ("/vhr/admin/dictionaries", "Справочники", False),
                    ("/vhr/admin/regions", "Регионы", False),
                    ("/vhr/admin/banks", "Банки", False),
                ],
            },
        ],
    },
]


def _all_links():
    for section in MENU:
        for col in section["columns"]:
            for link in col["links"]:
                yield link


def all_functional_paths():
    return [path for (path, _, functional) in _all_links() if functional]


def all_stub_paths():
    result = []
    for section in MENU:
        for col in section["columns"]:
            for path, label, functional in col["links"]:
                if not functional:
                    result.append((path, label, section["label"]))
    return result

"""
Конфиг левого меню — сознательно похож по структуре на реальные модули
Verifix (см. PROJECT_CONTEXT.md §6: hrm/href/hpd/htt/hsm/hpr/hide).

Каждый пункт: (path, label, functional). functional=True — реальная
страница с БД (регистрируется явно в main.py). functional=False —
заглушка ("в разработке"), регистрируется автоматически в main.py по
этому списку — так пункты меню и реальные роуты не расходятся.

Держим функциональные пути == путям в static/tour/steps.js, чтобы тур
(модель A) работал на этих страницах без доработки селекторов.
"""

MENU = [
    {
        "module": "hrm",
        "label": "Оргструктура (hrm)",
        "links": [
            ("/vhr/hrm/division_list", "Подразделения", True),
            ("/vhr/hrm/job_list", "Должности", True),
            ("/vhr/hrm/rank_list", "Ставки и разряды", False),
            ("/vhr/hrm/staff_units", "Штатные слоты", False),
            ("/vhr/hrm/org_chart", "Организационная схема", False),
        ],
    },
    {
        "module": "href",
        "label": "Персонал (href)",
        "links": [
            ("/vhr/href/employee", "Сотрудники", True),
            ("/vhr/href/employee_documents", "Документы сотрудников", False),
            ("/vhr/href/employee_profile", "Профили", False),
        ],
    },
    {
        "module": "hpd",
        "label": "Кадровые операции (hpd)",
        "links": [
            ("/vhr/hpd/hiring", "Приём на работу", False),
            ("/vhr/hpd/transfer", "Переводы", False),
            ("/vhr/hpd/dismissal", "Увольнения", False),
            ("/vhr/hpd/schedule_change", "Изменение графика/ставки", False),
        ],
    },
    {
        "module": "htt",
        "label": "Учёт времени (htt)",
        "links": [
            ("/vhr/htt/schedule_list", "Графики работы", True),
            ("/vhr/htt/location_list", "Локации", True),
            ("/vhr/htt/attendance_mark", "Отметки (симуляция)", True),
            ("/vhr/htt/timesheet_report", "Отчёт по часам", True),
            ("/vhr/htt/calendar", "Производственный календарь", False),
            ("/vhr/htt/tracks", "Треки перемещений", False),
        ],
    },
    {
        "module": "hsm",
        "label": "Сменное планирование (hsm)",
        "links": [
            ("/vhr/hsm/shifts", "Смены", False),
            ("/vhr/hsm/shift_groups", "Группы смен", False),
        ],
    },
    {
        "module": "hpr",
        "label": "Расчёт зарплаты (hpr)",
        "links": [
            ("/vhr/hpr/charges", "Начисления", False),
            ("/vhr/hpr/statements", "Ведомости", False),
            ("/vhr/hpr/payments", "Выплаты", False),
        ],
    },
    {
        "module": "hide",
        "label": "Формулы (hide)",
        "links": [
            ("/vhr/hide/formula_builder", "Конструктор формул", False),
        ],
    },
]


def all_functional_paths():
    return [path for section in MENU for (path, _, functional) in section["links"] if functional]


def all_stub_paths():
    return [(path, label, section["label"]) for section in MENU for (path, label, functional) in section["links"] if not functional]

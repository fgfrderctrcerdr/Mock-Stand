"""
Конфиг верхнего меню — по СКРИНШОТАМ реального Verifix (не по внутренним
кодам PL/SQL-модулей, как в первой версии — это была ошибка: реальные
разделы верхнего меню называются по бизнес-функциям, а не hrm/htt/href).

Реальная верхняя навигация: Кадры, Посещения, Эффективность, Зарплата,
Развитие, Отчётность, Рекрутинг, Настройки.

functional=True — реальная страница с БД. functional=False — заглушка.
"""

MENU = [
    {
        "key": "kadry",
        "label": "Кадры",
        "links": [
            ("/vhr/href/employee", "Сотрудники", True),
            ("/vhr/hpd/hiring", "Приём на работу", False),
            ("/vhr/hpd/transfer", "Переводы", False),
            ("/vhr/hpd/dismissal", "Увольнения", False),
            ("/vhr/href/employee_documents", "Документы сотрудников", False),
        ],
    },
    {
        "key": "poseshcheniya",
        "label": "Посещения",
        "links": [
            ("/vhr/htt/schedule_list", "Графики работы", True),
            ("/vhr/htt/location_list", "Локации", True),
            ("/vhr/htt/attendance_mark", "Отметки", True),
            ("/vhr/htt/calendar", "Производственный календарь", False),
            ("/vhr/htt/tracks", "Треки перемещений", False),
        ],
    },
    {
        "key": "effektivnost",
        "label": "Эффективность",
        "links": [
            ("/vhr/hsm/kpi", "KPI", False),
            ("/vhr/hsm/reviews", "Оценки", False),
        ],
    },
    {
        "key": "zarplata",
        "label": "Зарплата",
        "links": [
            ("/vhr/hpr/charges", "Начисления", False),
            ("/vhr/hpr/statements", "Ведомости", False),
            ("/vhr/hpr/payments", "Выплаты", False),
        ],
    },
    {
        "key": "razvitie",
        "label": "Развитие",
        "links": [
            ("/vhr/hsm/training", "Обучение", False),
            ("/vhr/hsm/growth_plans", "Планы развития", False),
        ],
    },
    {
        "key": "otchetnost",
        "label": "Отчётность",
        "links": [
            ("/vhr/htt/timesheet_report", "Отчёт по часам", True),
            ("/vhr/hpr/payroll_report", "Отчёт по зарплате", False),
        ],
    },
    {
        "key": "rekruting",
        "label": "Рекрутинг",
        "links": [
            ("/vhr/hpd/vacancies", "Вакансии", False),
            ("/vhr/hpd/candidates", "Кандидаты", False),
        ],
    },
    {
        "key": "nastroyki",
        "label": "Настройки",
        "links": [
            ("/vhr/hrm/division_list", "Подразделения", True),
            ("/vhr/hrm/job_list", "Должности", True),
            ("/vhr/admin/users", "Пользователи", True),
            ("/vhr/admin/roles", "Роли", False),
            ("/vhr/admin/dictionaries", "Справочники", False),
            ("/vhr/admin/regions", "Регионы", False),
            ("/vhr/admin/banks", "Банки", False),
        ],
    },
]


def all_functional_paths():
    return [path for section in MENU for (path, _, functional) in section["links"] if functional]


def all_stub_paths():
    return [(path, label, section["label"]) for section in MENU for (path, label, functional) in section["links"] if not functional]

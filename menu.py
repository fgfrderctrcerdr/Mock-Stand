"""
Верхняя навигация — по РЕАЛЬНЫМ скриншотам дропдаунов (не по прежним
догадкам). Верхний уровень теперь: Кадры, Посещения, Управление сменами,
Зарплата, Отчётность, Настройки.

Метки (label/title) теперь КЛЮЧИ ПЕРЕВОДА (см. TRANSLATIONS в main.py),
не литеральный русский текст — локализация (запрос Vladimir), рендерятся
через {{ t(label) }} в base.html, не напрямую.
"""

MENU = [
    {
        "key": "kadry",
        "label": "menu.kadry",
        "columns": [
            {
                "title": "menu.col.glavnoe",
                "links": [
                    ("/vhr/href/employee", "menu.sotrudniki", True),
                ],
            },
            {
                "title": "menu.col.organizatsiya",
                "links": [
                    ("/vhr/hrm/division_list", "menu.podrazdeleniya", True),
                    ("/vhr/hrm/retail_points", "menu.torg_tochki", False),
                    ("/vhr/hrm/job_list", "menu.dolzhnosti", True),
                ],
            },
            {
                "title": "menu.col.dashboard",
                "links": [
                    ("/vhr/hrm/division_stats", "menu.div_stats", False),
                    ("/vhr/hrm/report_queue", "menu.report_queue", False),
                    ("/vhr/hrm/year_summary", "menu.year_summary", False),
                ],
            },
        ],
    },
    {
        "key": "poseshcheniya",
        "label": "menu.poseshcheniya",
        "columns": [
            {
                "title": None,
                "links": [
                    ("/vhr/htt/schedule_list", "menu.grafiki_raboty", True),
                    ("/vhr/htt/absence_requests", "menu.otsutstvie", False),
                    ("/vhr/htt/schedule_change_requests", "menu.izm_grafika", False),
                    ("/vhr/htt/location_requests", "menu.zapros_lokatsiya", False),
                    ("/vhr/htt/overtime_requests", "menu.sverhurochnye_zapros", False),
                    ("/vhr/htt/mark_requests", "menu.zapros_otmetki", False),
                    ("/vhr/htt/overtime", "menu.sverhurochnye", False),
                    ("/vhr/htt/location_list", "menu.lokatsii", True),
                    ("/vhr/htt/devices", "menu.ustroystva", False),
                    ("/vhr/htt/attendance_mark", "menu.otmetki", True),
                    ("/vhr/htt/individual_schedules", "menu.indiv_grafiki", False),
                    ("/vhr/htt/timetables", "menu.raspisaniya", False),
                    ("/vhr/htt/timetable_change_requests", "menu.izm_raspisaniya", False),
                ],
            },
        ],
    },
    {
        "key": "smeny",
        "label": "menu.smeny",
        "columns": [
            {
                "title": None,
                "links": [
                    ("/vhr/hsm/shift_templates", "menu.shablony_smen", False),
                    ("/vhr/hsm/shift_assignment", "menu.naznachenie_smen", False),
                ],
            },
        ],
    },
    {
        "key": "zarplata",
        "label": "menu.zarplata",
        "columns": [
            {
                "title": None,
                "links": [
                    ("/vhr/hpr/charges", "menu.nachisleniya", False),
                    ("/vhr/hpr/statements", "menu.vedomosti", False),
                    ("/vhr/hpr/payments", "menu.vyplaty", False),
                ],
            },
        ],
    },
    {
        "key": "otchetnost",
        "label": "menu.otchetnost",
        "columns": [
            {
                "title": None,
                "links": [
                    ("/vhr/htt/timesheet_report", "menu.otchet_chasy", True),
                    ("/vhr/hpr/payroll_report", "menu.otchet_zarplata", False),
                ],
            },
        ],
    },
    {
        "key": "nastroyki",
        "label": "menu.nastroyki",
        "columns": [
            {
                "title": "menu.col.administrirovanie",
                "links": [
                    ("/vhr/admin/users", "menu.polzovateli", True),
                    ("/vhr/admin/roles", "menu.roli", False),
                ],
            },
            {
                "title": "menu.col.spravochniki",
                "links": [
                    ("/vhr/admin/dictionaries", "menu.spravochniki", False),
                    ("/vhr/admin/regions", "menu.regiony", False),
                    ("/vhr/admin/banks", "menu.banki", False),
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

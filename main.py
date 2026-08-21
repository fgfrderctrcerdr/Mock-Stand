"""
Verifix Mock-Stand — учебная копия интерфейса Verifix.

Не настоящий Verifix и не тур поверх него (это модель A в основном
проекте) — свой собственный веб-сервис, который повторяет навигацию
и стиль Verifix ровно настолько, чтобы:
  1. дать среду для практики самостоятельного онбординга без риска
     сломать боевой стенд;
  2. дать модели A (verifix-tour.js) реальные, не черновые селекторы —
     см. static/tour/steps.js;
  3. довести двух ключевых JTBD до результата: (1) сотрудник привязан
     к графику+локации и отметился, (2) виден отчёт по отработанным
     часам.

Сессия — не логин: cookie mock_org на каждый браузер, один cookie =
одна изолированная песочница (Organization). Middleware сама создаёт
Organization при первом заходе.
"""

from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import os
import time
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from db import Base, SessionLocal, engine
from menu import MENU, all_stub_paths
from models import (
    AttendanceEvent,
    Division,
    Employee,
    Location,
    Organization,
    Position,
    Schedule,
    TelemetryEvent,
    division_locations,
    employee_locations,
)

from contextlib import asynccontextmanager

BASE_DIR = Path(__file__).parent

# Портировано из старого standalone-концепта (web_onboarding/static/i18n.js,
# app.js) по просьбе Vladimir после пилотного теста с CPO — тексты и набор
# сфер/ролей там уже проверены, не придумываю заново.

INDUSTRIES = [
    ("retail", "industry.retail"),
    ("food", "industry.food"),
    ("it", "industry.it"),
    ("manuf", "industry.manuf"),
    ("edu", "industry.edu"),
    ("health", "industry.health"),
    ("other", "industry.other"),
]

ADMIN_ROLES = [
    ("owner", "role.owner"),
    ("hr", "role.hr"),
    ("lead", "role.lead"),
    ("fin", "role.fin"),
]

# Типовые подразделения/должности по сфере — как «Back of House / Front of
# House» в 7shifts. Показываются чипами на страницах Подразделения/Должности,
# клик по чипу сразу создаёт запись (см. соответствующие шаблоны).
DIVISION_SUGGESTIONS = {
    "retail": ["Продажи", "Склад", "Администрация"],
    "food": ["Кухня", "Зал", "Администрация"],
    "it": ["Разработка", "Продажи", "Администрация"],
    "manuf": ["Производство", "Склад", "Администрация"],
    "edu": ["Учебная часть", "Администрация"],
    "health": ["Приём", "Лаборатория", "Администрация"],
    "other": ["Основной отдел", "Администрация"],
}

POSITION_SUGGESTIONS = {
    "retail": ["Продавец", "Кассир", "Администратор", "Менеджер", "Кладовщик"],
    "food": ["Официант", "Повар", "Бариста", "Хостес", "Администратор"],
    "it": ["Разработчик", "Тестировщик", "Дизайнер", "Менеджер проекта", "DevOps"],
    "manuf": ["Оператор", "Мастер", "Технолог", "Кладовщик", "Контролёр ОТК"],
    "edu": ["Преподаватель", "Методист", "Администратор", "Ассистент"],
    "health": ["Врач", "Медсестра", "Администратор", "Лаборант"],
    "other": ["Менеджер", "Специалист", "Ассистент", "Администратор"],
}



@asynccontextmanager
async def lifespan(app: FastAPI):
    # QA-фикс №18: @app.on_event("startup") устарел в текущей версии FastAPI,
    # официально рекомендован lifespan-контекстменеджер.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Verifix Mock-Stand", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# QA (Railway, найдено Claude Code): версия ассетов для cache-busting —
# на Railway берём хэш коммита (стабилен в пределах деплоя, меняется на
# новом — см. static_cache_headers ниже), локально — таймстамп старта
# процесса (тоже стабилен, пока uvicorn не перезапущен).
ASSET_VERSION = os.environ.get("RAILWAY_GIT_COMMIT_SHA") or str(int(time.time()))
templates.env.globals["asset_version"] = ASSET_VERSION


def name_by_id(items, item_id):
    for it in items:
        if it.id == item_id:
            return it.name if hasattr(it, "name") else it.full_name
    return "—"


templates.env.globals["name_by_id"] = name_by_id


# ============================================================
# Org-сессия по cookie (см. docstring выше)
# ============================================================

COOKIE_NAME = "mock_org"
LANG_COOKIE_NAME = "mock_lang"


# ============================================================
# Локализация (запрос Vladimir: переключатель ru/uz в любой момент).
# current_lang — contextvar, выставляется в OrgSessionMiddleware из cookie
# на каждый запрос; t() читает его сама, поэтому в шаблонах достаточно
# {{ t('key') }} без протаскивания lang через каждый ctx вручную.
# Для JS (verifix-tour.js/steps.js) тот же словарь целиком уходит в
# window.VERIFIX_I18N через base.html (см. base_ctx).
# ============================================================

current_lang: ContextVar[str] = ContextVar("current_lang", default="ru")

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        # --- Верхняя навигация (menu.py) ---
        "menu.kadry": "Кадры", "menu.poseshcheniya": "Посещения", "menu.smeny": "Управление сменами",
        "menu.zarplata": "Зарплата", "menu.otchetnost": "Отчётность", "menu.nastroyki": "Настройки",
        "menu.col.glavnoe": "Главное", "menu.col.organizatsiya": "Организация", "menu.col.dashboard": "Дашборд",
        "menu.col.administrirovanie": "Администрирование", "menu.col.spravochniki": "Справочники",
        "menu.sotrudniki": "Сотрудники", "menu.podrazdeleniya": "Подразделения", "menu.torg_tochki": "Торговые точки",
        "menu.dolzhnosti": "Должности", "menu.div_stats": "Статистика работы подразделений",
        "menu.report_queue": "Очередь отчётов", "menu.year_summary": "Итоги года",
        "menu.grafiki_raboty": "Графики работы", "menu.otsutstvie": "Запросы на отсутствие",
        "menu.izm_grafika": "Запросы на изменение графика", "menu.zapros_lokatsiya": "Запросы на локацию",
        "menu.sverhurochnye_zapros": "Запросы на сверхурочные", "menu.zapros_otmetki": "Запросы на отметки",
        "menu.sverhurochnye": "Сверхурочные", "menu.lokatsii": "Локации", "menu.ustroystva": "Устройства",
        "menu.otmetki": "Отметки", "menu.indiv_grafiki": "Индивидуальные графики", "menu.raspisaniya": "Расписания",
        "menu.izm_raspisaniya": "Запросы на изменение расписания",
        "menu.shablony_smen": "Шаблоны смен", "menu.naznachenie_smen": "Назначение смен",
        "menu.nachisleniya": "Начисления", "menu.vedomosti": "Ведомости", "menu.vyplaty": "Выплаты",
        "menu.otchet_chasy": "Отчёт по часам", "menu.otchet_zarplata": "Отчёт по зарплате",
        "menu.polzovateli": "Пользователи", "menu.roli": "Роли", "menu.spravochniki": "Справочники",
        "menu.regiony": "Регионы", "menu.banki": "Банки",

        # --- Общий UI тура ---
        "tour.title": "Настройка Verifix", "tour.collapse": "Свернуть", "tour.expand": "Развернуть весь список",
        "tour.now": "Сейчас:", "tour.next": "Далее →", "tour.waiting": "Ждём выполнения на странице…",
        "tour.notfound": "Элемент не найден на экране — селектор уточним под стенд.",
        "tour.open_screen": "Открыть экран", "tour.yes": "Да", "tour.no": "Нет",
        "tour.start_over": "↺ Начать с начала",
        "tour.start_over_confirm": "Удалить все данные этой песочницы (подразделения, сотрудников и т.д.) и начать настройку с первого шага?",
        "tour.next_callout": "Это кнопка «Далее» — она всегда будет в этом углу экрана и переводит к следующему шагу настройки, когда вы будете готовы.",
        "tour.next_callout_ok": "Понятно",
        "tour.done": "Настройка завершена!",
        "tour.min_done": "Минимум выполнен — можно добавить ещё",
        "tour.list_empty_warning": "Список пока пуст — добавьте хотя бы одну запись, иначе следующие шаги не будет к чему привязать.",
        "tour.done_next": "Готово, дальше",
        "tour.welcome": "Добро пожаловать",
        "tour.start": "Начать",
        "lang.switch_ru": "RU", "lang.switch_uz": "UZ",
        "intro.title": "Добро пожаловать в песочницу Verifix",
        "intro.text": "Это учебная копия интерфейса — здесь можно потренироваться в настройке без риска сломать боевые данные. Начнём с пары вопросов о компании, а дальше проведём по шагам: от подразделений до первого отчёта по отработанным часам.",
        "intro.cta": "Начать настройку",

        # --- Заголовки страниц (page_title) ---
        "page.home": "Главная", "page.divisions": "Подразделения", "page.positions": "Должности",
        "page.locations": "Локации", "page.schedules": "Графики работы", "page.employees": "Сотрудники",
        "page.users": "Пользователи", "page.attendance": "Отметки", "page.report": "Отчёт по посещениям",
        "stub.text": "Этот раздел — навигационная заглушка мок-стенда: показывает, что в реальном Verifix здесь есть отдельный экран, но функциональность сюда не переносилась (она не нужна для сценариев, которые отрабатывает этот тур).",

        # --- Шаги тура (steps.js) ---
        "step.company.title": "Расскажите о компании",
        "step.company.why": "Название, сфера деятельности и ваша роль — это подберёт типовые подразделения и должности под вас.",
        "step.company.emptyWarning": "Заполните название компании, сферу деятельности и свою роль — без этого нельзя продолжить.",

        "step.locations.title": "Добавьте локацию",
        "step.locations.why": "Место, где сотрудник отмечает приход/уход.",
        "step.locations.emptyWarning": "Локация — это место, где сотрудник отмечает приход/уход. Без неё физически негде будет отметиться.",

        "step.divisions.title": "Создайте подразделения",
        "step.divisions.why": "Оргструктура компании. К подразделениям привязываются сотрудники.",
        "step.divisions.emptyWarning": "Подразделения — это структура компании (цех, зал, офис). Без хотя бы одного не к чему будет привязать сотрудников на следующих шагах.",

        "step.positions.title": "Заведите должности",
        "step.positions.why": "Должность определяет, кем работает сотрудник.",
        "step.positions.emptyWarning": "Должность — это то, кем работает сотрудник (например, «Официант»). Без неё не получится завести сотрудника.",

        "step.schedules.title": "Создайте график работы",
        "step.schedules.why": "Правила рабочего времени, которые назначаются сотрудникам.",
        "step.schedules.emptyWarning": "График определяет, когда сотрудник должен быть на работе. Без него система не поймёт, что считать опозданием или переработкой.",

        "step.employees.title": "Добавьте сотрудника",
        "step.employees.why": "Свяжите подразделение, должность и график в одном сотруднике — локацию прикрепим отдельным шагом дальше.",
        "step.employees.emptyWarning": "Сотрудник — это тот, кто и будет отмечаться и получать зарплату. Без него оставшиеся шаги (приглашение, отметка, отчёт) не имеют смысла.",

        "step.attach_employee.title": "Прикрепите сотрудника к локации",
        "step.attach_employee.why": "Перетащите КОНКРЕТНОГО сотрудника (аватар внутри карточки подразделения выше) на круг локации — прикрепится только он. Один человек может быть прикреплён сразу к нескольким локациям.",
        "step.attach_employee.emptyWarning": "Пока ни один сотрудник не прикреплён ни к одной локации — без этого не с чем будет считать отчёт по конкретной точке.",

        "step.attach_division.title": "Прикрепите ВСЁ подразделение к локации",
        "step.attach_division.why": "Перетащите тёмную ШАПКУ карточки подразделения (не отдельного сотрудника) на круг локации — прикрепятся СРАЗУ ВСЕ сотрудники этого подразделения (можно и через корневой узел компании — тащить всю компанию целиком).",
        "step.attach_division.emptyWarning": "Это отдельное действие от прикрепления одного сотрудника — попробуйте перетащить именно шапку карточки подразделения, целиком.",
        "step.attach_division.confirm": "Не всем сотрудникам прикреплена локация. Это значит, что вы не сможете на 100% быть уверены в том, что данные сотрудники сделали свою отметку на рабочем месте. Уверены, что хотите продолжить?",

        "step.invite.title": "Пригласите сотрудника в приложение",
        "step.invite.why": "Как в реальном Verifix: телефон + инвайт. Без этого нет способа сотруднику отметиться.",
        "step.invite.emptyWarning": "Не все сотрудники приглашены — без приглашения у них не будет доступа к приложению, значит, физически нечем будет сделать отметку.",

        "step.attendance.title": "Посмотрите отметки посещений",
        "step.attendance.why": "Здесь видны отметки прихода/ухода добавленных сотрудников. Если никто ещё не отмечался — список пустой, это нормально: шаг просто показывает, куда смотреть, действие не обязательно.",
        "step.attendance.doneHint": "Здесь видны отметки прихода/ухода сотрудников — список может быть пустым, если никто ещё не отмечался. Когда посмотрели — жмите «Далее».",

        "step.report.title": "Посмотрите отчёт по посещениям",
        "step.report.why": "Отчёт по отработанным часам — в формате как в реальном Verifix. Если отметок ещё не было, отчёт будет пустым, это тоже нормально.",
        "step.report.doneHint": "Отчёт по отработанным часам — как в реальном Verifix. Пусто, если ещё не было отметок — это нормально.",

        # --- Общие переиспользуемые строки ---
        "common.delete": "Удалить", "common.save_error": "Не удалось сохранить — проверьте соединение и попробуйте снова.",
        "common.top_level_option": "— верхний уровень —",

        # --- Подразделения (division_list.html) ---
        "div_page.title": "Подразделения",
        "div_page.subtitle": "Можно вкладывать подразделения друг в друга — просто перетащите строку на другую.",
        "div_page.make_root": "↥ сделать верхним уровнем",
        "div_page.parent_label": "Родитель:",
        "div_page.parent_aria": "Родительское подразделение для «{name}» (альтернатива drag-and-drop)",
        "div_page.delete_confirm": "Удалить «{name}»? Дочерние подразделения (если есть) будут перепривязаны на уровень выше.",
        "div_page.empty": "Пока не добавлено",
        "div_page.dnd_hint": "Перетащите строку на другую мышью — или выберите родителя в списке рядом (клавиатурная альтернатива drag-and-drop).",
        "div_page.suggestions_label": "Типовые для вашей сферы:",
        "div_page.name_label": "Как называется ваш отдел",
        "div_page.name_placeholder": "Кухня",
        "div_page.parent_field_label": "Какому отделу он подчиняется (опционально)",
        "div_page.submit": "+ Добавить подразделение",
        "div_page.reparent_error": "Не удалось перенести подразделение",

        # --- Общие переиспользуемые (для страниц ниже — во избежание дублей) ---
        "common.empty": "Пока не добавлено", "common.suggestions_label": "Типовые для вашей сферы:",
        "common.name_col": "Название",

        # --- Должности (job_list.html) ---
        "job_page.title": "Должности",
        "job_page.subtitle": "Кем работает сотрудник (Официант, Повар, Бариста…).",
        "job_page.delete_confirm": "Удалить должность «{name}»?",
        "job_page.name_label": "Название должности",
        "job_page.name_placeholder": "Официант",
        "job_page.submit": "+ Добавить должность",

        # --- Дни недели (короткие) — переиспользуются в schedule_list.html и в панели (schedule_summary) ---
        "weekday.mon": "Пн", "weekday.tue": "Вт", "weekday.wed": "Ср", "weekday.thu": "Чт",
        "weekday.fri": "Пт", "weekday.sat": "Сб", "weekday.sun": "Вс",

        # --- Графики работы (schedule_list.html) ---
        "sch_page.title": "Графики работы",
        "sch_page.subtitle": "Правила рабочего времени, которые назначаются сотрудникам.",
        "sch_page.kind_col": "Вид", "sch_page.details_col": "Детали",
        "sch_page.kind_regular": "Обычный", "sch_page.kind_hourly": "Почасовой",
        "sch_page.days_per_week": "{days} дн/нед", "sch_page.norm_label": "норма {hours} ч",
        "sch_page.delete_confirm": "Удалить график «{name}»?",
        "sch_page.template_label": "Шаблон",
        "sch_page.tpl_5_2": "Пятидневка (5/2, 9:00–18:00)", "sch_page.tpl_6_1": "Шестидневка (6/1, 9:00–18:00)",
        "sch_page.tpl_hourly": "Почасовой (норма 12 ч)", "sch_page.tpl_custom": "Кастомный",
        "sch_page.name_label": "Название графика", "sch_page.name_placeholder": "Дневная смена 9–18",
        "sch_page.workdays_legend": "Рабочие дни",
        "sch_page.start_label": "Начало", "sch_page.end_label": "Конец",
        "sch_page.norm_hours_label": "Норма часов",
        "sch_page.submit": "+ Добавить график",

        # --- Локации (location_list.html) ---
        "loc_page.title": "Локации",
        "loc_page.subtitle": "Место, где сотрудники отмечают приход и уход (зона вокруг точки на карте).",
        "loc_page.address_col": "Адрес", "loc_page.radius_col": "Радиус зоны, м",
        "loc_page.delete_confirm": "Удалить локацию «{name}»?",
        "loc_page.name_label": "Как называется ваша локация", "loc_page.name_placeholder": "Кафе на Мустакиллик",
        "loc_page.address_label": "По какому адресу находится ваша локация. С помощью адреса определим gps координаты",
        "loc_page.address_placeholder": "Введите адрес и нажмите «Найти»", "loc_page.find_btn": "Найти",
        "loc_page.coords_empty": "Координаты не выбраны — введите адрес или кликните на карте.",
        "loc_page.coords_selected": "Координаты: {lat}, {lng}",
        "loc_page.radius_label": "Радиус зоны, м",
        "loc_page.submit": "+ Добавить локацию",
        "loc_page.address_not_found": "Адрес не найден — попробуйте уточнить запрос или кликните точку на карте вручную.",
        "loc_page.geocode_error": "Ошибка геокодинга — попробуйте позже или кликните точку на карте вручную.",
        "loc_page.pick_point_first": "Сначала выберите точку на карте или найдите адрес.",

        # --- Сотрудники (employee_list.html) ---
        "emp_page.title": "Сотрудники",
        "emp_page.subtitle": "Свяжите сотрудника с подразделением, должностью, графиком и телефоном — без этого он не сможет отметить приход и получить приглашение.",
        "emp_page.fio_col": "ФИО", "emp_page.division_col": "Подразделение", "emp_page.position_col": "Должность",
        "emp_page.schedule_col": "График", "emp_page.location_col": "Локация",
        "emp_page.no_locations": "Локаций пока нет",
        "emp_page.delete_confirm": "Удалить сотрудника «{name}»?",
        "emp_page.fio_label": "ФИО", "emp_page.fio_placeholder": "Иванов Иван",
        "emp_page.division_label": "Подразделение", "emp_page.position_label": "Должность", "emp_page.schedule_label": "График",
        "emp_page.phone_label": "Номер телефона", "emp_page.phone_placeholder": "+998 90 123 45 67",
        "emp_page.location_hint": "Локацию (можно несколько) прикрепите после создания — перетащите сотрудника на неё в панели справа, или выберите в списке выше.",
        "emp_page.submit": "+ Добавить сотрудника",
        "emp_page.sync_error": "Не удалось сохранить локации",

        # --- Пользователи (users_list.html) ---
        "users_page.title": "Пользователи",
        "users_page.subtitle": "Приглашение сотрудника в приложение отметок — как в реальном Verifix (Настройки → Администрирование → Пользователи → тумблер «Телефон + invite»).",
        "users_page.phone_col": "Телефон", "users_page.status_col": "Статус",
        "users_page.phone_aria": "Телефон сотрудника {name}",
        "users_page.invite_title": "Заполните телефон, чтобы отправить приглашение",
        "users_page.invite_btn": "Пригласить",
        "users_page.status_none": "Не приглашён", "users_page.status_invited": "Приглашён",
        "users_page.empty": "Сначала добавьте сотрудников в разделе «Кадры → Сотрудники»",
        "users_page.hint": "Сотрудник получает SMS и сам подтверждает приглашение в приложении.",

        # --- Отметки (attendance_mark.html) ---
        "am_page.title": "Отметки",
        "am_page.subtitle": "Список отметок прихода/ухода — как в реальном Verifix, это просмотровая страница: отметки приходят от устройств/приложения, здесь их вручную не создают.",
        "am_page.person_col": "Физическое лицо", "am_page.location_col": "Локация",
        "am_page.kind_col": "Тип отметки", "am_page.date_col": "Дата создания",
        "am_page.kind_in": "Приход", "am_page.kind_out": "Уход",
        "am_page.empty": "Отметок пока нет — они появятся здесь, когда сотрудники начнут отмечаться в приложении Verifix ID.",

        # --- Отчёт по посещениям (timesheet_report.html) ---
        "rep_page.title": "Отчёт по посещениям",
        "rep_page.period": "Период: {start} – {end}. Показаны только реальные отметки — если их ещё не было, ячейки пустые, это нормально.",
        "rep_page.total_col": "Итого", "rep_page.day_off": "В", "rep_page.hour_suffix": "ч",
        "rep_page.empty": "Сотрудников пока нет",

        # --- Сообщения об ошибках валидации (redirect_with_error) ---
        "err.company_name_empty": "Название компании не может быть пустым.",
        "err.company_industry_required": "Выберите сферу деятельности из списка.",
        "err.company_role_required": "Выберите, кем вы являетесь в компании.",
        "err.division_name_empty": "Название подразделения не может быть пустым.",
        "err.position_name_empty": "Название должности не может быть пустым.",
        "err.location_name_empty": "Название локации не может быть пустым.",
        "err.location_coords_invalid": "Не удалось определить координаты — карта могла не успеть загрузиться. Кликните точку на карте или найдите адрес заново.",
        "err.location_radius_not_number": "Радиус зоны отметок должен быть числом.",
        "err.location_radius_positive": "Радиус зоны отметок должен быть больше нуля.",
        "err.schedule_name_empty": "Название графика не может быть пустым.",
        "err.schedule_kind_unknown": "Неизвестный вид графика.",
        "err.schedule_no_workdays": "У обычного графика должен быть хотя бы один рабочий день.",
        "err.schedule_bad_weekday": "Некорректный день недели.",
        "err.schedule_weekday_range": "День недели должен быть от 1 (понедельник) до 7 (воскресенье).",
        "err.schedule_times_required": "Укажите начало и конец рабочего дня.",
        "err.schedule_end_before_start": "Конец рабочего дня должен быть позже начала (ночные смены через полночь — отдельный случай, здесь не поддержан).",
        "err.schedule_norm_positive": "Норма часов должна быть больше нуля.",
        "err.employee_name_empty": "ФИО сотрудника не может быть пустым.",
        "err.employee_fields_required": "Заполните подразделение, должность, график и телефон. Локацию можно прикрепить позже — перетащите сотрудника на неё в панели справа.",
        "err.user_phone_empty": "Номер телефона не может быть пустым.",

        # --- Панель оргструктуры справа (base.html) — был пропущен целиком в первом заходе ---
        "ovp.org_structure": "Оргструктура",
        "ovp.drag_division_hint": "Перетащите на локацию, чтобы прикрепить ВСЕХ сотрудников этого подразделения",
        "ovp.drag_employee_suffix": " — перетащите на локацию",
        "ovp.no_employees": "Пока нет сотрудников",
        "ovp.child_divisions_count": "Подразделений: {count}",
        "ovp.drag_company_hint": "Перетащите на локацию, чтобы прикрепить ВСЕХ сотрудников компании",
        "ovp.company_fallback": "Компания",
        "ovp.no_divisions": "Подразделений пока нет",
        "ovp.schedules_title": "Графики",
        "ovp.locations_title": "Локации",
        "ovp.locations_hint": "Перетащите сотрудника ИЛИ целое подразделение (за шапку карточки) сюда, чтобы прикрепить. Один человек может быть прикреплён к нескольким локациям — перетаскивание добавляет, не заменяет. Клик по аватару внутри круга — снять именно эту локацию.",
        "ovp.show_all_employees": "Показать всех {count} сотрудников",
        "ovp.click_to_detach_suffix": " — клик, чтобы снять с этой локации",
        "ovp.click_to_detach_title": "Клик — снять с этой локации",
        "ovp.detach_division_title": "Открепить «{name}» от этой локации (снимет ВСЕХ сотрудников подразделения)",
        "ovp.attach_error": "Не удалось прикрепить",
        "ovp.detach_confirm": "Снять «{name}» с этой локации?",
        "ovp.detach_error": "Не удалось снять локацию",
        "ovp.detach_division_confirm": "Открепить «{name}» от этой локации? Все сотрудники подразделения будут откреплены от неё.",
        "ovp.detach_division_error": "Не удалось открепить подразделение",
        "ovp.employee_word": "сотрудник",

        # --- Профиль компании (home.html) ---
        "home.title": "Расскажите о компании",
        "home.subtitle": "Эти данные подберут типовые подразделения и должности под вашу сферу — не придётся заводить всё с нуля.",
        "home.company_name": "Название компании",
        "home.company_name_placeholder": "Например, GrandPharm",
        "home.industry_label": "Сфера деятельности",
        "home.industry_choose": "Выберите сферу…",
        "home.industry_hint": "Подберём типовые должности и подразделения для этой сферы.",
        "home.role_label": "Кем вы являетесь в компании?",
        "home.role_choose": "Выберите роль…",
        "home.submit": "Сохранить и продолжить",
        "industry.retail": "Розница и торговля", "industry.food": "Общепит и HoReCa", "industry.it": "IT и услуги",
        "industry.manuf": "Производство", "industry.edu": "Образование", "industry.health": "Медицина", "industry.other": "Другое",
        "role.owner": "Владелец бизнеса", "role.hr": "HR-менеджер", "role.lead": "Руководитель отдела", "role.fin": "Бухгалтер / финансы",
    },
    "uz": {
        "menu.kadry": "Kadrlar", "menu.poseshcheniya": "Tashriflar", "menu.smeny": "Smenalarni boshqarish",
        "menu.zarplata": "Ish haqi", "menu.otchetnost": "Hisobotlar", "menu.nastroyki": "Sozlamalar",
        "menu.col.glavnoe": "Asosiy", "menu.col.organizatsiya": "Tashkilot", "menu.col.dashboard": "Boshqaruv paneli",
        "menu.col.administrirovanie": "Administrator", "menu.col.spravochniki": "Ma'lumotnomalar",
        "menu.sotrudniki": "Xodimlar", "menu.podrazdeleniya": "Bo'limlar", "menu.torg_tochki": "Savdo nuqtalari",
        "menu.dolzhnosti": "Lavozimlar", "menu.div_stats": "Bo'limlar statistikasi",
        "menu.report_queue": "Hisobotlar navbati", "menu.year_summary": "Yil natijalari",
        "menu.grafiki_raboty": "Ish grafiklari", "menu.otsutstvie": "Yo'qlik so'rovlari",
        "menu.izm_grafika": "Grafikni o'zgartirish so'rovlari", "menu.zapros_lokatsiya": "Lokatsiya so'rovlari",
        "menu.sverhurochnye_zapros": "Qo'shimcha ish so'rovlari", "menu.zapros_otmetki": "Belgilar so'rovlari",
        "menu.sverhurochnye": "Qo'shimcha ish", "menu.lokatsii": "Lokatsiyalar", "menu.ustroystva": "Qurilmalar",
        "menu.otmetki": "Belgilar", "menu.indiv_grafiki": "Individual grafiklar", "menu.raspisaniya": "Jadvallar",
        "menu.izm_raspisaniya": "Jadvalni o'zgartirish so'rovlari",
        "menu.shablony_smen": "Smena shablonlari", "menu.naznachenie_smen": "Smena tayinlash",
        "menu.nachisleniya": "Hisoblashlar", "menu.vedomosti": "Vedomostlar", "menu.vyplaty": "To'lovlar",
        "menu.otchet_chasy": "Soatlar hisoboti", "menu.otchet_zarplata": "Ish haqi hisoboti",
        "menu.polzovateli": "Foydalanuvchilar", "menu.roli": "Rollar", "menu.spravochniki": "Ma'lumotnomalar",
        "menu.regiony": "Hududlar", "menu.banki": "Banklar",

        "tour.title": "Verifix sozlamalari", "tour.collapse": "Yopish", "tour.expand": "To'liq ro'yxatni ochish",
        "tour.now": "Hozir:", "tour.next": "Keyingisi →", "tour.waiting": "Sahifada bajarilishini kutmoqdamiz…",
        "tour.notfound": "Ekranda element topilmadi — selektor stendga moslashtiriladi.",
        "tour.open_screen": "Ekranni ochish", "tour.yes": "Ha", "tour.no": "Yo'q",
        "tour.start_over": "↺ Boshidan boshlash",
        "tour.start_over_confirm": "Ushbu sandbox'ning barcha ma'lumotlari (bo'limlar, xodimlar va h.k.) o'chirilib, sozlash birinchi qadamdan boshlansinmi?",
        "tour.next_callout": "Bu «Keyingisi» tugmasi — u har doim ekranning shu burchagida bo'ladi va tayyor bo'lganingizda keyingi qadamga o'tkazadi.",
        "tour.next_callout_ok": "Tushunarli",
        "tour.done": "Sozlash yakunlandi!",
        "tour.min_done": "Minimum bajarildi — yana qo'shishingiz mumkin",
        "tour.list_empty_warning": "Ro'yxat hali bo'sh — kamida bitta yozuv qo'shing, aks holda keyingi qadamlarda bog'lashga hech narsa bo'lmaydi.",
        "tour.done_next": "Tayyor, keyingisi",
        "tour.welcome": "Xush kelibsiz",
        "tour.start": "Boshlash",
        "lang.switch_ru": "RU", "lang.switch_uz": "UZ",
        "intro.title": "Verifix sinov maydoniga xush kelibsiz",
        "intro.text": "Bu — interfeysning o'quv nusxasi: bu yerda haqiqiy ma'lumotlarni buzish xavfisiz sozlashni mashq qilish mumkin. Kompaniya haqida bir nechta savoldan boshlaymiz, keyin esa bosqichma-bosqich — bo'limlardan tortib ishlangan soatlar bo'yicha birinchi hisobotgacha olib boramiz.",
        "intro.cta": "Sozlashni boshlash",

        "page.home": "Bosh sahifa", "page.divisions": "Bo'limlar", "page.positions": "Lavozimlar",
        "page.locations": "Lokatsiyalar", "page.schedules": "Ish grafiklari", "page.employees": "Xodimlar",
        "page.users": "Foydalanuvchilar", "page.attendance": "Belgilar", "page.report": "Tashriflar hisoboti",
        "stub.text": "Bu bo'lim — mock-stend navigatsiya zaglushkasi: haqiqiy Verifix'da bu yerda alohida ekran borligini ko'rsatadi, lekin funksionallik bu yerga ko'chirilmagan (u ushbu tur ishlab chiqadigan stsenariylar uchun kerak emas).",

        # --- Шаги тура (steps.js) ---
        "step.company.title": "Kompaniya haqida ma'lumot bering",
        "step.company.why": "Nomi, faoliyat sohasi va sizning rolingiz — shular asosida sohangiz uchun odatiy bo'limlar va lavozimlar tanlanadi.",
        "step.company.emptyWarning": "Kompaniya nomi, faoliyat sohasi va rolingizni to'ldiring — bularsiz davom etib bo'lmaydi.",

        "step.locations.title": "Lokatsiya qo'shing",
        "step.locations.why": "Xodim kelish/ketishni belgilaydigan joy.",
        "step.locations.emptyWarning": "Lokatsiya — xodim kelish/ketishni belgilaydigan joy. Bo'lmasa, jismonan belgi qo'yishga joy bo'lmaydi.",

        "step.divisions.title": "Bo'limlarni yarating",
        "step.divisions.why": "Kompaniyaning tashkiliy tuzilishi. Xodimlar bo'limlarga bog'lanadi.",
        "step.divisions.emptyWarning": "Bo'limlar — kompaniya tuzilishi (sex, zal, ofis). Hech bo'lmaganda bittasi bo'lmasa, keyingi qadamlarda xodimlarni bog'lashga hech narsa bo'lmaydi.",

        "step.positions.title": "Lavozimlarni kiriting",
        "step.positions.why": "Lavozim xodim kim bo'lib ishlashini belgilaydi.",
        "step.positions.emptyWarning": "Lavozim — xodim kim bo'lib ishlashini bildiradi (masalan, «Ofitsiant»). Bo'lmasa, xodim qo'shib bo'lmaydi.",

        "step.schedules.title": "Ish grafigini yarating",
        "step.schedules.why": "Xodimlarga tayinlanadigan ish vaqti qoidalari.",
        "step.schedules.emptyWarning": "Grafik xodim qachon ishda bo'lishi kerakligini belgilaydi. Bo'lmasa, tizim kechikish yoki qo'shimcha ishlashni tushunmaydi.",

        "step.employees.title": "Xodim qo'shing",
        "step.employees.why": "Bo'lim, lavozim va grafikni bitta xodimga bog'lang — lokatsiyani keyingi alohida qadamda biriktiramiz.",
        "step.employees.emptyWarning": "Xodim — belgi qo'yadigan va ish haqi oladigan shaxs. Bo'lmasa, qolgan qadamlar (taklif, belgi, hisobot) ma'nosiz bo'ladi.",

        "step.attach_employee.title": "Xodimni lokatsiyaga biriktiring",
        "step.attach_employee.why": "ANIQ bir xodimni (yuqoridagi bo'lim kartochkasi ichidagi avatar) lokatsiya doirasiga tortib olib boring — faqat u biriktiriladi. Bir kishi bir vaqtning o'zida bir nechta lokatsiyaga biriktirilishi mumkin.",
        "step.attach_employee.emptyWarning": "Hozircha birorta xodim biror lokatsiyaga biriktirilmagan — bo'lmasa, aniq nuqta bo'yicha hisobotni hisoblashga hech narsa bo'lmaydi.",

        "step.attach_division.title": "BUTUN bo'limni lokatsiyaga biriktiring",
        "step.attach_division.why": "Bo'lim kartochkasining qorong'i SARLAVHASINI (alohida xodimni emas) lokatsiya doirasiga tortib olib boring — bu bo'limning BARCHA xodimlari BIRDANIGA biriktiriladi (kompaniyaning ildiz tugunini tortib, butun kompaniyani ham biriktirish mumkin).",
        "step.attach_division.emptyWarning": "Bu bitta xodimni biriktirishdan alohida harakat — aynan bo'lim kartochkasining sarlavhasini butunlay tortib ko'ring.",
        "step.attach_division.confirm": "Barcha xodimlarga lokatsiya biriktirilmagan. Bu shuni anglatadiki, ushbu xodimlar ish joyida belgi qo'yganiga 100% ishonch hosil qila olmaysiz. Davom etishga ishonchingiz komilmi?",

        "step.invite.title": "Xodimni ilovaga taklif qiling",
        "step.invite.why": "Haqiqiy Verifix'dagidek: telefon + taklif. Bo'lmasa, xodimning belgi qo'yishga imkoni yo'q.",
        "step.invite.emptyWarning": "Barcha xodimlar taklif qilinmagan — taklifsiz ularda ilovaga kirish imkoni bo'lmaydi, demak, jismonan belgi qo'yishning iloji yo'q.",

        "step.attendance.title": "Tashrif belgilarini ko'ring",
        "step.attendance.why": "Bu yerda qo'shilgan xodimlarning kelish/ketish belgilari ko'rinadi. Hali hech kim belgi qo'ymagan bo'lsa — ro'yxat bo'sh, bu normal holat: qadam shunchaki qayerga qarash kerakligini ko'rsatadi, harakat shart emas.",
        "step.attendance.doneHint": "Bu yerda xodimlarning kelish/ketish belgilari ko'rinadi — agar hali hech kim belgi qo'ymagan bo'lsa, ro'yxat bo'sh bo'lishi mumkin. Ko'rib chiqqach — «Keyingisi» tugmasini bosing.",

        "step.report.title": "Tashriflar hisobotini ko'ring",
        "step.report.why": "Ishlangan soatlar hisoboti — haqiqiy Verifix'dagidek formatda. Agar hali belgilar bo'lmasa, hisobot bo'sh bo'ladi, bu ham normal holat.",
        "step.report.doneHint": "Ishlangan soatlar hisoboti — haqiqiy Verifix'dagidek. Agar hali belgilar bo'lmasa, bo'sh — bu normal holat.",

        # --- Профиль компании (home.html) ---
        "home.title": "Kompaniya haqida ma'lumot bering",
        "home.subtitle": "Bu ma'lumotlar sohangiz uchun odatiy bo'limlar va lavozimlarni tanlaydi — hammasini noldan kiritishga hojat qolmaydi.",
        "home.company_name": "Kompaniya nomi",
        "home.company_name_placeholder": "Masalan, GrandPharm",
        "home.industry_label": "Faoliyat sohasi",
        "home.industry_choose": "Sohani tanlang…",
        "home.industry_hint": "Ushbu soha uchun odatiy lavozim va bo'limlarni tanlaymiz.",
        "home.role_label": "Kompaniyada kim bo'lasiz?",
        "home.role_choose": "Rolni tanlang…",
        "home.submit": "Saqlash va davom etish",
        "industry.retail": "Chakana va savdo", "industry.food": "Umumiy ovqatlanish va HoReCa", "industry.it": "IT va xizmatlar",
        "industry.manuf": "Ishlab chiqarish", "industry.edu": "Ta'lim", "industry.health": "Tibbiyot", "industry.other": "Boshqa",
        "role.owner": "Biznes egasi", "role.hr": "HR-menejer", "role.lead": "Bo'lim rahbari", "role.fin": "Buxgalter / moliya",

        "common.delete": "O'chirish", "common.save_error": "Saqlab bo'lmadi — aloqani tekshirib, qayta urinib ko'ring.",
        "common.top_level_option": "— yuqori daraja —",

        "div_page.title": "Bo'limlar",
        "div_page.subtitle": "Bo'limlarni bir-biriga joylashtirish mumkin — qatorni boshqasiga sudrab olib boring.",
        "div_page.make_root": "↥ eng yuqori daraja qilish",
        "div_page.parent_label": "Ota bo'lim:",
        "div_page.parent_aria": "«{name}» uchun ota bo'lim (drag-and-drop muqobili)",
        "div_page.delete_confirm": "«{name}» o'chirilsinmi? Bola bo'limlar (agar bo'lsa) bir daraja yuqoriga qayta bog'lanadi.",
        "div_page.empty": "Hali qo'shilmagan",
        "div_page.dnd_hint": "Qatorni sichqoncha bilan boshqasiga tortib olib boring — yoki yonidagi ro'yxatdan ota bo'limni tanlang (drag-and-drop'ning klaviatura muqobili).",
        "div_page.suggestions_label": "Sohangiz uchun odatiy:",
        "div_page.name_label": "Bo'limingiz qanday nomlanadi",
        "div_page.name_placeholder": "Oshxona",
        "div_page.parent_field_label": "U qaysi bo'limga bo'ysunadi (ixtiyoriy)",
        "div_page.submit": "+ Bo'lim qo'shish",
        "div_page.reparent_error": "Bo'limni ko'chirib bo'lmadi",

        "common.empty": "Hali qo'shilmagan", "common.suggestions_label": "Sohangiz uchun odatiy:",
        "common.name_col": "Nomi",

        "job_page.title": "Lavozimlar",
        "job_page.subtitle": "Xodim kim bo'lib ishlaydi (Ofitsiant, Oshpaz, Barista…).",
        "job_page.delete_confirm": "«{name}» lavozimi o'chirilsinmi?",
        "job_page.name_label": "Lavozim nomi",
        "job_page.name_placeholder": "Ofitsiant",
        "job_page.submit": "+ Lavozim qo'shish",

        "weekday.mon": "Du", "weekday.tue": "Se", "weekday.wed": "Cho", "weekday.thu": "Pay",
        "weekday.fri": "Ju", "weekday.sat": "Sha", "weekday.sun": "Yak",

        "sch_page.title": "Ish grafiklari",
        "sch_page.subtitle": "Xodimlarga tayinlanadigan ish vaqti qoidalari.",
        "sch_page.kind_col": "Turi", "sch_page.details_col": "Tafsilotlar",
        "sch_page.kind_regular": "Oddiy", "sch_page.kind_hourly": "Soatlik",
        "sch_page.days_per_week": "{days} kun/hafta", "sch_page.norm_label": "norma {hours} soat",
        "sch_page.delete_confirm": "«{name}» grafigi o'chirilsinmi?",
        "sch_page.template_label": "Shablon",
        "sch_page.tpl_5_2": "Besh kunlik (5/2, 9:00–18:00)", "sch_page.tpl_6_1": "Olti kunlik (6/1, 9:00–18:00)",
        "sch_page.tpl_hourly": "Soatlik (norma 12 soat)", "sch_page.tpl_custom": "Maxsus",
        "sch_page.name_label": "Grafik nomi", "sch_page.name_placeholder": "Kunduzgi smena 9–18",
        "sch_page.workdays_legend": "Ish kunlari",
        "sch_page.start_label": "Boshlanishi", "sch_page.end_label": "Tugashi",
        "sch_page.norm_hours_label": "Soatlar normasi",
        "sch_page.submit": "+ Grafik qo'shish",

        "loc_page.title": "Lokatsiyalar",
        "loc_page.subtitle": "Xodimlar kelish va ketishni belgilaydigan joy (xaritadagi nuqta atrofidagi zona).",
        "loc_page.address_col": "Manzil", "loc_page.radius_col": "Zona radiusi, m",
        "loc_page.delete_confirm": "«{name}» lokatsiyasi o'chirilsinmi?",
        "loc_page.name_label": "Lokatsiyangiz qanday nomlanadi", "loc_page.name_placeholder": "Mustaqillikdagi kafe",
        "loc_page.address_label": "Lokatsiyangiz qaysi manzilda joylashgan. Manzil orqali GPS koordinatalarini aniqlaymiz",
        "loc_page.address_placeholder": "Manzilni kiriting va «Topish»ni bosing", "loc_page.find_btn": "Topish",
        "loc_page.coords_empty": "Koordinatalar tanlanmagan — manzilni kiriting yoki xaritada bosing.",
        "loc_page.coords_selected": "Koordinatalar: {lat}, {lng}",
        "loc_page.radius_label": "Zona radiusi, m",
        "loc_page.submit": "+ Lokatsiya qo'shish",
        "loc_page.address_not_found": "Manzil topilmadi — so'rovni aniqlashtiring yoki xaritada nuqtani qo'lda bosing.",
        "loc_page.geocode_error": "Geokodlash xatosi — keyinroq urinib ko'ring yoki xaritada nuqtani qo'lda bosing.",
        "loc_page.pick_point_first": "Avval xaritada nuqtani tanlang yoki manzilni toping.",

        "emp_page.title": "Xodimlar",
        "emp_page.subtitle": "Xodimni bo'lim, lavozim, grafik va telefon bilan bog'lang — bularsiz u kelishini belgilay olmaydi va taklif ololmaydi.",
        "emp_page.fio_col": "F.I.Sh.", "emp_page.division_col": "Bo'lim", "emp_page.position_col": "Lavozim",
        "emp_page.schedule_col": "Grafik", "emp_page.location_col": "Lokatsiya",
        "emp_page.no_locations": "Hali lokatsiyalar yo'q",
        "emp_page.delete_confirm": "«{name}» xodimi o'chirilsinmi?",
        "emp_page.fio_label": "F.I.Sh.", "emp_page.fio_placeholder": "Ivanov Ivan",
        "emp_page.division_label": "Bo'lim", "emp_page.position_label": "Lavozim", "emp_page.schedule_label": "Grafik",
        "emp_page.phone_label": "Telefon raqami", "emp_page.phone_placeholder": "+998 90 123 45 67",
        "emp_page.location_hint": "Lokatsiyani (bir nechtasi mumkin) yaratgandan keyin biriktiring — xodimni o'ng paneldagi lokatsiyaga tortib olib boring, yoki yuqoridagi ro'yxatdan tanlang.",
        "emp_page.submit": "+ Xodim qo'shish",
        "emp_page.sync_error": "Lokatsiyalarni saqlab bo'lmadi",

        "users_page.title": "Foydalanuvchilar",
        "users_page.subtitle": "Xodimni belgilar ilovasiga taklif qilish — haqiqiy Verifix'dagidek (Sozlamalar → Administrator → Foydalanuvchilar → «Telefon + invite» tugmasi).",
        "users_page.phone_col": "Telefon", "users_page.status_col": "Holat",
        "users_page.phone_aria": "{name} xodimining telefoni",
        "users_page.invite_title": "Taklif yuborish uchun telefonni to'ldiring",
        "users_page.invite_btn": "Taklif qilish",
        "users_page.status_none": "Taklif qilinmagan", "users_page.status_invited": "Taklif qilingan",
        "users_page.empty": "Avval «Kadrlar → Xodimlar» bo'limida xodimlarni qo'shing",
        "users_page.hint": "Xodim SMS oladi va ilovada taklifni o'zi tasdiqlaydi.",

        "am_page.title": "Belgilar",
        "am_page.subtitle": "Kelish/ketish belgilari ro'yxati — haqiqiy Verifix'dagidek, bu ko'rish uchun sahifa: belgilar qurilma/ilovadan keladi, bu yerda ularni qo'lda yaratilmaydi.",
        "am_page.person_col": "Jismoniy shaxs", "am_page.location_col": "Lokatsiya",
        "am_page.kind_col": "Belgi turi", "am_page.date_col": "Yaratilgan sana",
        "am_page.kind_in": "Kelish", "am_page.kind_out": "Ketish",
        "am_page.empty": "Hozircha belgilar yo'q — xodimlar Verifix ID ilovasida belgilana boshlashi bilan bu yerda paydo bo'ladi.",

        "rep_page.title": "Tashriflar hisoboti",
        "rep_page.period": "Davr: {start} – {end}. Faqat haqiqiy belgilar ko'rsatilgan — agar ular hali bo'lmasa, katakchalar bo'sh, bu normal holat.",
        "rep_page.total_col": "Jami", "rep_page.day_off": "D", "rep_page.hour_suffix": "s",
        "rep_page.empty": "Hozircha xodimlar yo'q",

        "err.company_name_empty": "Kompaniya nomi bo'sh bo'lishi mumkin emas.",
        "err.company_industry_required": "Ro'yxatdan faoliyat sohasini tanlang.",
        "err.company_role_required": "Kompaniyada kim ekanligingizni tanlang.",
        "err.division_name_empty": "Bo'lim nomi bo'sh bo'lishi mumkin emas.",
        "err.position_name_empty": "Lavozim nomi bo'sh bo'lishi mumkin emas.",
        "err.location_name_empty": "Lokatsiya nomi bo'sh bo'lishi mumkin emas.",
        "err.location_coords_invalid": "Koordinatalarni aniqlab bo'lmadi — xarita ulgurmagan bo'lishi mumkin. Xaritada nuqtani bosing yoki manzilni qayta toping.",
        "err.location_radius_not_number": "Zona radiusi son bo'lishi kerak.",
        "err.location_radius_positive": "Zona radiusi noldan katta bo'lishi kerak.",
        "err.schedule_name_empty": "Grafik nomi bo'sh bo'lishi mumkin emas.",
        "err.schedule_kind_unknown": "Grafik turi noma'lum.",
        "err.schedule_no_workdays": "Oddiy grafikda kamida bitta ish kuni bo'lishi kerak.",
        "err.schedule_bad_weekday": "Hafta kuni noto'g'ri.",
        "err.schedule_weekday_range": "Hafta kuni 1 (dushanba) dan 7 (yakshanba) gacha bo'lishi kerak.",
        "err.schedule_times_required": "Ish kunining boshlanishi va tugashini ko'rsating.",
        "err.schedule_end_before_start": "Ish kunining tugashi boshlanishidan keyin bo'lishi kerak (yarim tunni kesib o'tadigan tungi smenalar — alohida holat, bu yerda qo'llab-quvvatlanmaydi).",
        "err.schedule_norm_positive": "Soatlar normasi noldan katta bo'lishi kerak.",
        "err.employee_name_empty": "Xodim F.I.Sh. bo'sh bo'lishi mumkin emas.",
        "err.employee_fields_required": "Bo'lim, lavozim, grafik va telefonni to'ldiring. Lokatsiyani keyinroq biriktirish mumkin — xodimni o'ng paneldagi lokatsiyaga tortib olib boring.",
        "err.user_phone_empty": "Telefon raqami bo'sh bo'lishi mumkin emas.",

        "ovp.org_structure": "Tashkiliy tuzilma",
        "ovp.drag_division_hint": "Bu bo'limning BARCHA xodimlarini biriktirish uchun lokatsiyaga tortib olib boring",
        "ovp.drag_employee_suffix": " — lokatsiyaga tortib olib boring",
        "ovp.no_employees": "Hali xodimlar yo'q",
        "ovp.child_divisions_count": "Bo'limlar: {count}",
        "ovp.drag_company_hint": "Kompaniyaning BARCHA xodimlarini biriktirish uchun lokatsiyaga tortib olib boring",
        "ovp.company_fallback": "Kompaniya",
        "ovp.no_divisions": "Hali bo'limlar yo'q",
        "ovp.schedules_title": "Grafiklar",
        "ovp.locations_title": "Lokatsiyalar",
        "ovp.locations_hint": "Xodimni YOKI butun bo'limni (kartochka sarlavhasidan) bu yerga tortib olib boring, biriktirish uchun. Bir kishi bir nechta lokatsiyaga biriktirilishi mumkin — tortish qo'shadi, almashtirmaydi. Doira ichidagi avatarga bosish — aynan shu lokatsiyani olib tashlaydi.",
        "ovp.show_all_employees": "Barcha {count} xodimni ko'rsatish",
        "ovp.click_to_detach_suffix": " — ushbu lokatsiyadan olib tashlash uchun bosing",
        "ovp.click_to_detach_title": "Bosing — bu lokatsiyadan olib tashlanadi",
        "ovp.detach_division_title": "«{name}»ni bu lokatsiyadan ajratish (bo'limning BARCHA xodimlarini olib tashlaydi)",
        "ovp.attach_error": "Biriktirib bo'lmadi",
        "ovp.detach_confirm": "«{name}» ushbu lokatsiyadan olib tashlansinmi?",
        "ovp.detach_error": "Lokatsiyani olib tashlab bo'lmadi",
        "ovp.detach_division_confirm": "«{name}» bu lokatsiyadan ajratilsinmi? Bo'limning barcha xodimlari undan ajratiladi.",
        "ovp.detach_division_error": "Bo'limni ajratib bo'lmadi",
        "ovp.employee_word": "xodim",
    },
}


def t(key: str, **kwargs) -> str:
    lang = current_lang.get()
    text = TRANSLATIONS.get(lang, {}).get(key) or TRANSLATIONS["ru"].get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text

templates.env.globals["t"] = t


class OrgSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # QA M1: раньше создавало Organization на ЛЮБОЙ запрос без cookie —
        # включая /static/*, /favicon.ico и т.п. Любой бот/скан/битая ссылка
        # плодит мусорные организации в БД, ничего не настраивая. Эти пути
        # не читают request.state.org/db вообще, пропускаем без сессии.
        path = request.url.path
        if path.startswith("/static/") or path == "/favicon.ico":
            return await call_next(request)

        # Локализация (запрос Vladimir): язык — тоже cookie, читаем его
        # здесь же в contextvar, чтобы t() работала из любого места
        # (шаблоны, helper-функции) без протаскивания lang через каждый
        # base_ctx() вручную. См. current_lang/t() выше.
        lang = request.cookies.get(LANG_COOKIE_NAME, "ru")
        if lang not in ("ru", "uz"):
            lang = "ru"
        lang_token = current_lang.set(lang)

        db = SessionLocal()
        token = request.cookies.get(COOKIE_NAME)
        org = db.query(Organization).filter(Organization.token == token).first() if token else None
        created = False
        if not org:
            org = Organization()
            db.add(org)
            db.commit()
            db.refresh(org)
            created = True

        org_token = org.token  # снимаем до db.close() — после close объект expired, атрибут не читается
        request.state.db = db
        request.state.org = org
        request.state.lang = lang
        try:
            response = await call_next(request)
        finally:
            db.close()
            current_lang.reset(lang_token)

        if created:
            response.set_cookie(COOKIE_NAME, org_token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365)
        return response


app.add_middleware(OrgSessionMiddleware)


@app.get("/set-lang/{lang}")
def set_lang(request: Request, lang: str):
    """Переключатель языка (см. запрос Vladimir) — cookie на год, редирект
    обратно на ту же страницу (Referer), не всегда на "/"."""
    if lang not in ("ru", "uz"):
        lang = "ru"
    back_to = request.headers.get("referer") or "/"
    response = RedirectResponse(url=back_to, status_code=303)
    response.set_cookie(LANG_COOKIE_NAME, lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


# QA (Railway, найдено Claude Code): раньше здесь было no-store на ЛЮБОЙ
# запрос под /static/ — оправдано только для локальной разработки (после
# git pull видеть свежий JS/CSS без танцев с кэшем), но на реальном
# деплое означает, что браузер ЗАНОВО перекачивает весь CSS/JS/Leaflet
# (~162 КБ) на КАЖДЫЙ переход между страницами — Mock-Stand подвисает
# только на Railway (сеть до CDN дольше, чем localhost). Fix: долгий
# иммутабельный кэш + версионирование URL (?v=...), а не отказ от кэша
# вообще — свежесть после деплоя достигается сменой ?v=, не сменой
# Cache-Control.
@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def log_event(request: Request, type_: str, meta: dict | None = None):
    db = request.state.db
    db.add(TelemetryEvent(organization_id=request.state.org.id, type=type_, path=request.url.path, meta=meta or {}))
    db.commit()


def build_org_snapshot(db, org):
    """Данные для постоянной панели «результат» справа (см. запрос
    Vladimir после пилота с CPO) — пересчитывается на КАЖДОЙ загрузке
    страницы из текущего состояния БД, поэтому правки на любом шаге сразу
    видны на панели, независимо от того, куда вернулся пользователь."""
    divisions = db.query(Division).filter_by(organization_id=org.id).all()
    employees = db.query(Employee).filter_by(organization_id=org.id).all()
    locations = db.query(Location).filter_by(organization_id=org.id).all()
    # CPO-фидбек: "показать должность рядом с ФИО сотрудника" — решил как
    # PM: не отдельная секция панели (для этого уже есть колонка "Должность"
    # в самой таблице сотрудников), а просто в подсказке (title) на аватаре
    # в дереве/локациях — не захламляет компактный вид панели.
    positions = db.query(Position).filter_by(organization_id=org.id).all()
    position_by_id = {p.id: p.name for p in positions}
    # CPO-фидбек: "добавить отображение графиков в правой части экрана" —
    # намеренно лаконично (одна строка на график, не карточка, как у
    # подразделений) — это дополнительная сводка, не основной элемент панели.
    schedules = db.query(Schedule).filter_by(organization_id=org.id).all()

    emp_by_division = defaultdict(list)
    emp_by_location = defaultdict(list)
    for e in employees:
        if e.division_id:
            emp_by_division[e.division_id].append(e)
        for loc in e.locations:   # многие-ко-многим — сотрудник может быть в нескольких списках локаций одновременно
            emp_by_location[loc.id].append(e)

    # Для подвала карточки (см. референс) — количество ПРЯМЫХ дочерних
    # подразделений у каждого узла.
    child_counts = defaultdict(int)
    for d in divisions:
        if d.parent_id:
            child_counts[d.parent_id] += 1

    def _attach_counts(nodes):
        for n in nodes:
            n["child_count"] = child_counts.get(n["division"].id, 0)
            _attach_counts(n["children"])
        return nodes

    division_tree = _attach_counts(_build_division_tree(divisions, emp_by_division))

    # Доработка (запрос Vladimir): показать в самой локации, какое
    # подразделение к ней прикреплено (постоянное правило, не отдельные
    # сотрудники) — читаем division_locations, а не выводим из фактических
    # привязок employee_locations (там могло быть добавлено и вручную,
    # по одному человеку, без правила на уровне подразделения).
    division_name_by_id = {d.id: d.name for d in divisions}
    divisions_by_location = defaultdict(list)
    for row in db.execute(division_locations.select()).all():
        dname = division_name_by_id.get(row.division_id)
        if dname:
            divisions_by_location[row.location_id].append({"id": row.division_id, "name": dname})

    loc_rows = [
        {
            "location": l,
            "employees": emp_by_location.get(l.id, []),
            "attached_divisions": divisions_by_location.get(l.id, []),
        }
        for l in locations
    ]
    # QA-фидбек Vladimir: раньше был отдельный плоский пул "не прикреплены" —
    # убран. Теперь источник для перетаскивания на локацию — САМИ карточки
    # подразделений в дереве выше (сотрудник всегда состоит в своём
    # подразделении независимо от прикрепления к локациям, поэтому дублировать
    # его в отдельном пуле не нужно — см. base.html, аватары внутри
    # .ovp__division теперь draggable).

    return {
        "division_tree": division_tree,
        "company_name": org.company_name,
        "loc_rows": loc_rows,
        "schedules": schedules,
        "position_by_id": position_by_id,
        "has_any": bool(divisions or employees or locations),
    }


def initials(full_name: str) -> str:
    parts = [p for p in full_name.strip().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def display_name(full_name: str) -> str:
    """Фамилия.И — по просьбе Vladimir: два инициала (initials()) не
    давали понять, кто именно это, в бейджах на панели-оргструктуре.
    Сотрудники заводятся в формате "Фамилия Имя" (см. placeholder формы
    сотрудника), поэтому первое слово — фамилия, второе — имя."""
    parts = [p for p in full_name.strip().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0]
    return parts[0] + "." + parts[1][0].upper()


# QA M3: время отметок хранится в UTC (правильно для БД), но отображалось
# без конвертации — для Ташкента это разница в 5 часов, сбивает восприятие
# демо ("вот сейчас отметился" показывало время на 5ч назад). Конвертируем
# только для отображения, храним всё так же в UTC.
TASHKENT_TZ = ZoneInfo("Asia/Tashkent")


def to_local(dt):
    if dt is None:
        return None
    return dt.astimezone(TASHKENT_TZ)


def employees_word(n: int) -> str:
    """Склонение "сотрудник/сотрудника/сотрудников" — для карточки
    подразделения в стиле реального Verifix (см. референс-скриншот).
    В узбекском склонения по числу нет (существительное неизменно) —
    просто одно слово независимо от n."""
    if current_lang.get() == "uz":
        return t("ovp.employee_word")
    n_abs = abs(n) % 100
    n1 = n_abs % 10
    if 11 <= n_abs <= 14:
        return "сотрудников"
    if n1 == 1:
        return "сотрудник"
    if 2 <= n1 <= 4:
        return "сотрудника"
    return "сотрудников"


WEEKDAY_KEYS = {1: "weekday.mon", 2: "weekday.tue", 3: "weekday.wed", 4: "weekday.thu", 5: "weekday.fri", 6: "weekday.sat", 7: "weekday.sun"}


def schedule_summary(s) -> str:
    """Компактная строка для панели (CPO: "лаконично") — не карточка,
    просто одна строка на график. Локализована (см. WEEKDAY_KEYS/t())."""
    if s.kind == "hourly":
        return t("sch_page.norm_label", hours=f"{s.norm_hours or 0:g}")
    days = "".join(t(WEEKDAY_KEYS[d]) for d in (s.week_days or []) if d in WEEKDAY_KEYS)
    return f"{s.start_time or '—'}–{s.end_time or '—'}, {days or '—'}"


def base_ctx(request: Request, page_title: str):
    current_section = None
    for section in MENU:
        for col in section["columns"]:
            for path, _, _ in col["links"]:
                if path == request.url.path:
                    current_section = section["label"]

    # Для гида по прикреплению к локации (два разных действия — DOM после
    # обоих выглядит ОДИНАКОВО, поэтому check() тура не может отличить их
    # по факту результата; смотрим на факт СОБЫТИЯ вместо этого).
    db = request.state.db
    org_id = request.state.org.id
    individual_attach_done = db.query(TelemetryEvent).filter_by(organization_id=org_id, type="individual_location_attach").first() is not None
    division_attach_done = db.query(TelemetryEvent).filter_by(organization_id=org_id, type="division_location_attach").first() is not None

    # CPO-фидбек: "система запрашивает подтверждение перехода, если не
    # все сотрудники привязаны к локации" — считаем это на сервере (проще
    # и надёжнее одного JOIN, чем гонять всех сотрудников в JS), кладём
    # как маркер для клиентской проверки перед "Далее" (см. steps.js
    # attach_division.confirmBeforeAdvance).
    has_unattached_employees = (
        db.query(Employee)
        .filter_by(organization_id=org_id)
        .filter(~Employee.locations.any())
        .first()
        is not None
    )

    # Уточнение Vladimir: шаг приглашения должен требовать ВСЕХ сотрудников
    # приглашёнными/активными, не "хотя бы одного" (как было раньше).
    # Уточнение Vladimir: концепт не должен требовать симуляции ПРИНЯТИЯ
    # приглашения (invite_status='active') — задача администратора
    # закончена в момент ОТПРАВКИ приглашения, дальше это уже действие
    # самого сотрудника (вне контроля админа, как и в реальности). Раньше
    # здесь стояло != "active", что требовало ещё и симулировать принятие.
    has_uninvited_employees = (
        db.query(Employee)
        .filter_by(organization_id=org_id)
        .filter(Employee.invite_status == "none")
        .first()
        is not None
    )
    # По запросу: подсказку на шаге приглашения показываем только ДО
    # первого успешного приглашения — дальше не навязываем на каждого
    # следующего сотрудника.
    has_any_invited = (
        db.query(Employee)
        .filter_by(organization_id=org_id)
        .filter(Employee.invite_status != "none")
        .first()
        is not None
    )

    return {
        "request": request,
        "page_title": page_title,
        "menu": MENU,
        "current_path": request.url.path,
        "current_section": current_section,
        "org_id": request.state.org.id,
        "error": request.query_params.get("error"),   # QA-фикс №4 — банер ошибки серверной валидации
        "org_snapshot": build_org_snapshot(request.state.db, request.state.org),
        "initials": initials,
        "display_name": display_name,
        "to_local": to_local,
        "employees_word": employees_word,
        "schedule_summary": schedule_summary,
        "individual_attach_done": individual_attach_done,
        "division_attach_done": division_attach_done,
        "has_unattached_employees": has_unattached_employees,
        "has_uninvited_employees": has_uninvited_employees,
        "has_any_invited": has_any_invited,
        "lang": current_lang.get(),
        # Для JS (verifix-tour.js/steps.js) — тот же словарь целиком, для
        # ТЕКУЩЕГО языка, сериализованный в base.html через |tojson.
        "i18n_json": TRANSLATIONS.get(current_lang.get(), TRANSLATIONS["ru"]),
    }


def redirect_with_error(path: str, message: str) -> RedirectResponse:
    """QA-фикс №4: сервер раньше принимал всё как есть (отрицательный
    радиус геозоны, график 18:00→09:00 без единого рабочего дня и т.п.).
    При невалидных данных редиректим назад на список с ?error=... —
    список читает его в base_ctx() и показывает банер (см. шаблоны)."""
    return RedirectResponse(url=f"{path}?error={quote(message)}", status_code=303)


# ============================================================
# Корень — нейтральная стартовая страница, НЕ форма создания.
#
# Раньше редиректило прямо на /vhr/hrm/division_list — из-за этого
# первый шаг тура сразу открывался в поле ввода, минуя верхнюю
# навигацию, что не похоже на то, как реально работают с Verifix
# (см. фидбек — переход должен идти через клик по меню, как в
# настоящем интерфейсе). Теперь первый шаг тура откроется как обычный
# route-переход: попап с кнопкой «Открыть экран» + сама верхняя
# навигация доступна для клика, как в реальном флоу.
# ============================================================

@app.get("/")
def root(request: Request):
    log_event(request, "page_view")
    org = request.state.org
    ctx = base_ctx(request, "page.home")
    ctx.update(
        industries=INDUSTRIES,
        admin_roles=ADMIN_ROLES,
        company_name=org.company_name or "",
        industry=org.industry or "",
        admin_role=org.admin_role or "",
    )
    return templates.TemplateResponse(request, "home.html", ctx)


@app.post("/")
def save_company(
    request: Request,
    company_name: str = Form(""),
    industry: str = Form(""),
    admin_role: str = Form(""),
):
    if not company_name.strip():
        return redirect_with_error("/", t('err.company_name_empty'))
    if industry not in dict(INDUSTRIES):
        return redirect_with_error("/", t('err.company_industry_required'))
    if admin_role not in dict(ADMIN_ROLES):
        return redirect_with_error("/", t('err.company_role_required'))

    db = request.state.db
    org = request.state.org
    org.company_name = company_name.strip()
    org.industry = industry
    org.admin_role = admin_role
    db.commit()
    log_event(request, "entity_created", {"entity": "company_profile"})
    return RedirectResponse(url="/", status_code=303)


@app.get("/reset")
def reset_sandbox(request: Request):
    """Полный сброс песочницы («Начать с начала» в топбаре). Удаляет
    текущую Organization целиком (со всей оргструктурой) и cookie —
    следующий запрос создаст свежую песочницу с нуля. Прогресс тура
    (localStorage) чистит сам фронт до перехода сюда — см. base.html.

    AttendanceEvent/TelemetryEvent не имеют cascade-связи с Organization
    (см. models.py) — удаляем явно, иначе останутся сиротами в БД."""
    db = request.state.db
    org = request.state.org
    db.query(AttendanceEvent).filter_by(organization_id=org.id).delete()
    db.query(TelemetryEvent).filter_by(organization_id=org.id).delete()
    db.delete(org)
    db.commit()
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


# ============================================================
# Подразделения (hrm)
# ============================================================

def _ordered_divisions(divisions):
    """DFS с сохранением глубины — для дерева с отступами (см. web_onboarding app.js).
    Используется на самой странице подразделений (DnD-список), НЕ путать
    с _build_division_tree ниже (вложенная структура для панели-оргчарта)."""
    by_parent = defaultdict(list)
    for d in divisions:
        by_parent[d.parent_id].append(d)
    result = []

    def walk(parent_id, depth):
        for d in by_parent.get(parent_id, []):
            result.append((d, depth))
            walk(d.id, depth + 1)

    walk(None, 0)
    return result


def _build_division_tree(divisions, emp_by_division):
    """Настоящее вложенное дерево (не плоский список с отступами) — для
    оргчарта в панели справа, по референсу реального Verifix: компания
    сверху, от неё ветками верхнеуровневые подразделения, под каждым —
    его дети, рекурсивно. Рендерится через recursive-макрос в base.html."""
    by_parent = defaultdict(list)
    for d in divisions:
        by_parent[d.parent_id].append(d)

    def build(parent_id):
        return [
            {"division": d, "employees": emp_by_division.get(d.id, []), "children": build(d.id)}
            for d in by_parent.get(parent_id, [])
        ]

    return build(None)


def _is_descendant(divisions, node_id, ancestor_id):
    """True, если node_id находится где-то в поддереве ancestor_id (защита от циклов при DnD)."""
    by_id = {d.id: d for d in divisions}
    cur = by_id.get(node_id)
    while cur and cur.parent_id:
        if cur.parent_id == ancestor_id:
            return True
        cur = by_id.get(cur.parent_id)
    return False


@app.get("/vhr/hrm/division_list")
def division_list(request: Request):
    db = request.state.db
    org = request.state.org
    divisions = db.query(Division).filter_by(organization_id=org.id).all()
    existing_names = {d.name.lower() for d in divisions}
    suggestions = [s for s in DIVISION_SUGGESTIONS.get(org.industry or "other", []) if s.lower() not in existing_names]
    log_event(request, "page_view")
    ctx = base_ctx(request, "page.divisions")
    ctx.update(
        divisions=divisions,
        ordered=_ordered_divisions(divisions),
        suggestions=suggestions,
    )
    return templates.TemplateResponse(request, "division_list.html", ctx)


@app.post("/vhr/hrm/division_list/create")
def division_create(request: Request, name: str = Form(""), parent_id: str = Form("")):
    if not name.strip():
        return redirect_with_error("/vhr/hrm/division_list", t('err.division_name_empty'))
    db = request.state.db
    org = request.state.org
    d = Division(organization_id=org.id, name=name.strip(), parent_id=parent_id or None)
    db.add(d)
    db.commit()
    log_event(request, "entity_created", {"entity": "division", "id": d.id})
    return RedirectResponse(url="/vhr/hrm/division_list", status_code=303)


@app.post("/vhr/hrm/division_list/{division_id}/delete")
def division_delete(request: Request, division_id: str):
    db = request.state.db
    org = request.state.org
    # Удаление с детьми → перепривязка детей вверх (как в web_onboarding QA-фиксе),
    # иначе дети сирот остаются с parent_id, ссылающимся на удалённую запись.
    target = db.query(Division).filter_by(id=division_id, organization_id=org.id).first()
    if target:
        db.query(Division).filter_by(organization_id=org.id, parent_id=division_id).update({"parent_id": target.parent_id})
        # QA H1: SQLite не форсит FK — без этого сотрудники этого подразделения
        # остаются ссылаться на удалённый id и пропадают из панели/отчётов
        # (не попадают ни в дерево, ни в "не прикреплены", просто исчезают).
        db.query(Employee).filter_by(organization_id=org.id, division_id=division_id).update({"division_id": None})
        db.execute(division_locations.delete().where(division_locations.c.division_id == division_id))
        db.delete(target)
        db.commit()
    return RedirectResponse(url="/vhr/hrm/division_list", status_code=303)


@app.post("/vhr/hrm/division_list/{division_id}/reparent")
def division_reparent(request: Request, division_id: str, new_parent_id: str = Form("")):
    """AJAX-эндпоинт для drag-and-drop дерева. Возвращает JSON, не редирект."""
    db = request.state.db
    org = request.state.org
    divisions = db.query(Division).filter_by(organization_id=org.id).all()
    new_parent_id = new_parent_id or None

    if new_parent_id == division_id:
        return {"ok": False, "error": "Нельзя сделать подразделение родителем самого себя"}
    if new_parent_id and _is_descendant(divisions, new_parent_id, division_id):
        return {"ok": False, "error": "Нельзя переносить подразделение в собственного потомка"}
    # QA M4: раньше не проверялось, что new_parent_id реально существует в
    # ЭТОЙ организации — искусственно составленный запрос мог подвесить
    # подразделение на недостижимый parent_id: оно тогда не попадает в
    # дерево (тот же паттерн, что и в H1 — висячая ссылка), но остаётся в
    # счётчике "всего подразделений", создавая расхождение.
    if new_parent_id and not any(d.id == new_parent_id for d in divisions):
        return {"ok": False, "error": "Родительское подразделение не найдено"}

    db.query(Division).filter_by(id=division_id, organization_id=org.id).update({"parent_id": new_parent_id})
    db.commit()
    return {"ok": True}


# ============================================================
# Должности (hrm)
# ============================================================

@app.get("/vhr/hrm/job_list")
def job_list(request: Request):
    db = request.state.db
    org = request.state.org
    positions = db.query(Position).filter_by(organization_id=org.id).all()
    existing_names = {p.name.lower() for p in positions}
    suggestions = [s for s in POSITION_SUGGESTIONS.get(org.industry or "other", []) if s.lower() not in existing_names]
    log_event(request, "page_view")
    ctx = base_ctx(request, "page.positions")
    ctx.update(positions=positions, suggestions=suggestions)
    return templates.TemplateResponse(request, "job_list.html", ctx)


@app.post("/vhr/hrm/job_list/create")
def job_create(request: Request, name: str = Form("")):
    if not name.strip():
        return redirect_with_error("/vhr/hrm/job_list", t('err.position_name_empty'))
    db = request.state.db
    org = request.state.org
    p = Position(organization_id=org.id, name=name.strip())
    db.add(p)
    db.commit()
    log_event(request, "entity_created", {"entity": "position", "id": p.id})
    return RedirectResponse(url="/vhr/hrm/job_list", status_code=303)


@app.post("/vhr/hrm/job_list/{position_id}/delete")
def job_delete(request: Request, position_id: str):
    db = request.state.db
    org = request.state.org
    # QA H1: обнуляем ссылку у сотрудников — иначе дальше "мертвый" position_id
    # (name_by_id молча вернёт "—", но данные в БД останутся противоречивыми).
    db.query(Employee).filter_by(organization_id=org.id, position_id=position_id).update({"position_id": None})
    db.query(Position).filter_by(id=position_id, organization_id=org.id).delete()
    db.commit()
    return RedirectResponse(url="/vhr/hrm/job_list", status_code=303)


# ============================================================
# Локации (htt)
# ============================================================

@app.get("/vhr/htt/location_list")
def location_list(request: Request):
    db = request.state.db
    org = request.state.org
    locations = db.query(Location).filter_by(organization_id=org.id).all()
    log_event(request, "page_view")
    ctx = base_ctx(request, "page.locations")
    ctx.update(locations=locations)
    return templates.TemplateResponse(request, "location_list.html", ctx)


@app.post("/vhr/htt/location_list/create")
def location_create(request: Request, name: str = Form(""), lat: str = Form(""), lng: str = Form(""), accuracy: str = Form("50"), address: str = Form("")):
    if not name.strip():
        return redirect_with_error("/vhr/htt/location_list", t('err.location_name_empty'))
    # QA H2: lat/lng были float = Form(...) (обязательные) — если карта
    # не прогрузилась (сеть/Leaflet не успел инициализироваться), скрытые
    # поля уходят пустыми, и это падало в сырой 422 (Field required) вместо
    # дружелюбного баннера, как везде. Теперь принимаем как строки и сами
    # валидируем, отдельно объясняя именно ЭТУ причину (не просто "проверьте
    # поле", а "карта не загрузилась" — это реальный частый триггер).
    try:
        lat_val = float(lat)
        lng_val = float(lng)
    except ValueError:
        return redirect_with_error(
            "/vhr/htt/location_list",
            t('err.location_coords_invalid')
        )
    # QA L1: accuracy тоже был типизирован как float = Form(50) — тот же
    # класс проблемы (сырой 422 на нечисловом крафте), а не просто "min=1".
    try:
        accuracy_val = float(accuracy)
    except ValueError:
        return redirect_with_error("/vhr/htt/location_list", t('err.location_radius_not_number'))
    if accuracy_val <= 0:
        return redirect_with_error("/vhr/htt/location_list", t('err.location_radius_positive'))
    db = request.state.db
    org = request.state.org
    l = Location(organization_id=org.id, name=name.strip(), address=address, lat=lat_val, lng=lng_val, accuracy=accuracy_val)
    db.add(l)
    db.commit()
    log_event(request, "entity_created", {"entity": "location", "id": l.id})
    return RedirectResponse(url="/vhr/htt/location_list", status_code=303)


@app.post("/vhr/htt/location_list/{location_id}/delete")
def location_delete(request: Request, location_id: str):
    db = request.state.db
    org = request.state.org
    # QA H1 (основной репродуцированный сценарий): без этого сотрудник
    # прикреплённый к удаляемой локации пропадает из панели ПОЛНОСТЬЮ.
    # Теперь связь многие-ко-многим через employee_locations — чистим
    # строки ассоциативной таблицы явно (bulk-delete Location.delete()
    # не трогает secondary-таблицу автоматически, тот же класс проблемы).
    db.execute(employee_locations.delete().where(employee_locations.c.location_id == location_id))
    db.execute(division_locations.delete().where(division_locations.c.location_id == location_id))
    db.query(Location).filter_by(id=location_id, organization_id=org.id).delete()
    db.commit()
    return RedirectResponse(url="/vhr/htt/location_list", status_code=303)


# ============================================================
# Графики работы (htt)
# ============================================================

@app.get("/vhr/htt/schedule_list")
def schedule_list(request: Request):
    db = request.state.db
    org = request.state.org
    schedules = db.query(Schedule).filter_by(organization_id=org.id).all()
    log_event(request, "page_view")
    ctx = base_ctx(request, "page.schedules")
    ctx.update(schedules=schedules)
    return templates.TemplateResponse(request, "schedule_list.html", ctx)


@app.post("/vhr/htt/schedule_list/create")
def schedule_create(
    request: Request,
    name: str = Form(""),
    kind: str = Form("regular"),
    week_days: list[str] = Form([]),
    start_time: str = Form(""),
    end_time: str = Form(""),
    norm_hours: str = Form(""),
):
    if not name.strip():
        return redirect_with_error("/vhr/htt/schedule_list", t('err.schedule_name_empty'))
    if kind not in ("regular", "hourly"):
        return redirect_with_error("/vhr/htt/schedule_list", t('err.schedule_kind_unknown'))

    if kind == "regular":
        if not week_days:
            return redirect_with_error("/vhr/htt/schedule_list", t('err.schedule_no_workdays'))
        # QA L1: int(d) без защиты падал в 500 на нечисловом крафте, и не было
        # проверки диапазона 1–7 (дни недели) — валидный HTML-чекбокс всегда
        # шлёт "1".."7", но эндпоинт не должен ронять сервер на произвольном вводе.
        try:
            week_days_int = sorted(set(int(d) for d in week_days))
        except ValueError:
            return redirect_with_error("/vhr/htt/schedule_list", t('err.schedule_bad_weekday'))
        if any(d < 1 or d > 7 for d in week_days_int):
            return redirect_with_error("/vhr/htt/schedule_list", t('err.schedule_weekday_range'))
        if not start_time or not end_time:
            return redirect_with_error("/vhr/htt/schedule_list", t('err.schedule_times_required'))
        if start_time >= end_time:
            return redirect_with_error("/vhr/htt/schedule_list", t('err.schedule_end_before_start'))

    if kind == "hourly":
        try:
            norm_val = float(norm_hours)
        except ValueError:
            norm_val = 0
        if norm_val <= 0:
            return redirect_with_error("/vhr/htt/schedule_list", t('err.schedule_norm_positive'))

    db = request.state.db
    org = request.state.org
    s = Schedule(
        organization_id=org.id,
        name=name.strip(),
        kind=kind,
        week_days=week_days_int if kind == "regular" else [],
        start_time=start_time or None if kind == "regular" else None,
        end_time=end_time or None if kind == "regular" else None,
        norm_hours=float(norm_hours) if (kind == "hourly" and norm_hours) else None,
    )
    db.add(s)
    db.commit()
    log_event(request, "entity_created", {"entity": "schedule", "id": s.id})
    return RedirectResponse(url="/vhr/htt/schedule_list", status_code=303)


@app.post("/vhr/htt/schedule_list/{schedule_id}/delete")
def schedule_delete(request: Request, schedule_id: str):
    db = request.state.db
    org = request.state.org
    db.query(Employee).filter_by(organization_id=org.id, schedule_id=schedule_id).update({"schedule_id": None})
    db.query(Schedule).filter_by(id=schedule_id, organization_id=org.id).delete()
    db.commit()
    return RedirectResponse(url="/vhr/htt/schedule_list", status_code=303)


# ============================================================
# Сотрудники (href)
# ============================================================

@app.get("/vhr/href/employee")
def employee_list(request: Request):
    db = request.state.db
    org = request.state.org
    employees = db.query(Employee).filter_by(organization_id=org.id).all()
    divisions = db.query(Division).filter_by(organization_id=org.id).all()
    positions = db.query(Position).filter_by(organization_id=org.id).all()
    schedules = db.query(Schedule).filter_by(organization_id=org.id).all()
    locations = db.query(Location).filter_by(organization_id=org.id).all()
    log_event(request, "page_view")
    ctx = base_ctx(request, "page.employees")
    ctx.update(employees=employees, divisions=divisions, positions=positions, schedules=schedules, locations=locations)
    return templates.TemplateResponse(request, "employee_list.html", ctx)


@app.post("/vhr/href/employee/create")
def employee_create(
    request: Request,
    full_name: str = Form(""),
    division_id: str = Form(""),
    position_id: str = Form(""),
    schedule_id: str = Form(""),
    phone: str = Form(""),
):
    # QA-фикс №10 (первая версия) требовал ВСЕ 4 связи при создании,
    # включая локацию. Пересмотрено дважды: сначала локация стала
    # необязательной (появился drag-and-drop), теперь поле локации убрано
    # из формы СОЗДАНИЯ совсем — раз сотрудник может быть прикреплён к
    # НЕСКОЛЬКИМ локациям (многие-ко-многим, см. Employee.locations),
    # единственное место назначения — панель справа (drag-and-drop или
    # мультиселект в списке сотрудников), не форма создания.
    if not full_name.strip():
        return redirect_with_error("/vhr/href/employee", t('err.employee_name_empty'))
    # Уточнение Vladimir (health check при создании): телефон тоже стал
    # обязательным наряду с подразделением/должностью/графиком — раньше
    # был необязательным, теперь требуется сразу, иначе позже пришлось бы
    # отдельно дозаполнять на странице "Пользователи" перед приглашением.
    if not (division_id and position_id and schedule_id and phone.strip()):
        return redirect_with_error(
            "/vhr/href/employee",
            t('err.employee_fields_required')
        )
    db = request.state.db
    org = request.state.org
    e = Employee(
        organization_id=org.id,
        full_name=full_name.strip(),
        division_id=division_id or None,
        position_id=position_id or None,
        schedule_id=schedule_id or None,
        phone=phone.strip() or None,   # необязательно — можно дозаполнить позже на странице "Пользователи"
    )
    db.add(e)
    db.commit()

    # QA-фикс (найден по фидбеку): "прикрепление подразделения к локации"
    # раньше действовало только на сотрудников, которые уже существовали
    # на момент перетаскивания. Новый сотрудник в это же подразделение
    # молча оставался непрёкреплённым. Теперь читаем ПРАВИЛА подразделения
    # (division_locations, см. models.py) и прикрепляем те же локации
    # новому сотруднику автоматически — правило действует и на будущих.
    if division_id:
        rule_location_ids = [
            row.location_id for row in
            db.execute(division_locations.select().where(division_locations.c.division_id == division_id)).all()
        ]
        if rule_location_ids:
            locs = db.query(Location).filter(Location.organization_id == org.id, Location.id.in_(rule_location_ids)).all()
            e.locations = locs
            db.commit()

    log_event(request, "entity_created", {"entity": "employee", "id": e.id})
    return RedirectResponse(url="/vhr/href/employee", status_code=303)


@app.post("/vhr/href/employee/{employee_id}/delete")
def employee_delete(request: Request, employee_id: str):
    db = request.state.db
    org = request.state.org
    # QA M6 + тот же паттерн для новой связи многие-ко-многим: чистим
    # AttendanceEvent и employee_locations явно перед удалением сотрудника.
    db.query(AttendanceEvent).filter_by(organization_id=org.id, employee_id=employee_id).delete()
    db.execute(employee_locations.delete().where(employee_locations.c.employee_id == employee_id))
    db.query(Employee).filter_by(id=employee_id, organization_id=org.id).delete()
    db.commit()
    return RedirectResponse(url="/vhr/href/employee", status_code=303)


@app.post("/vhr/href/employee/{employee_id}/assign_location")
def employee_assign_location(request: Request, employee_id: str, location_id: str = Form("")):
    """Drag-and-drop сотрудника на локацию в постоянной панели справа —
    ДОБАВЛЯЕТ локацию к сотруднику (не заменяет), т.к. связь
    многие-ко-многим (см. Employee.locations, запрос Vladimir: "1
    человек может быть прикреплён к нескольким локациям"). Идемпотентно —
    повторное прикрепление той же локации не создаёт дубликат и не
    считается ошибкой. AJAX, не редирект — панель сама перерисуется."""
    db = request.state.db
    org = request.state.org
    emp = db.query(Employee).filter_by(id=employee_id, organization_id=org.id).first()
    if not emp:
        return {"ok": False, "error": "Сотрудник не найден"}
    if not location_id:
        return {"ok": False, "error": "Локация не указана"}
    loc = db.query(Location).filter_by(id=location_id, organization_id=org.id).first()
    if not loc:
        return {"ok": False, "error": "Локация не найдена"}
    if loc not in emp.locations:
        emp.locations.append(loc)
        db.commit()
    log_event(request, "individual_location_attach", {"employee_id": employee_id, "location_id": location_id})
    return {"ok": True}


@app.post("/vhr/href/employee/{employee_id}/detach_location")
def employee_detach_location(request: Request, employee_id: str, location_id: str = Form("")):
    """Снять ОДНУ конкретную локацию с сотрудника (клик по аватару внутри
    круга локации в панели) — не трогает остальные его локации."""
    db = request.state.db
    org = request.state.org
    emp = db.query(Employee).filter_by(id=employee_id, organization_id=org.id).first()
    if not emp:
        return {"ok": False, "error": "Сотрудник не найден"}
    loc = db.query(Location).filter_by(id=location_id, organization_id=org.id).first()
    if loc and loc in emp.locations:
        emp.locations.remove(loc)
        db.commit()
    return {"ok": True}


@app.post("/vhr/href/employee/{employee_id}/sync_locations")
def employee_sync_locations(request: Request, employee_id: str, location_ids: list[str] = Form([])):
    """Полная замена набора локаций сотрудника — для мультиселекта в
    employee_list.html (QA M5, клавиатурная альтернатива drag-and-drop).
    В отличие от assign_location (добавляет одну), здесь пользователь явно
    выбрал ИТОГОВЫЙ набор в <select multiple>, поэтому заменяем целиком."""
    db = request.state.db
    org = request.state.org
    emp = db.query(Employee).filter_by(id=employee_id, organization_id=org.id).first()
    if not emp:
        return {"ok": False, "error": "Сотрудник не найден"}
    locs = db.query(Location).filter(Location.organization_id == org.id, Location.id.in_(location_ids)).all()
    emp.locations = locs
    db.commit()
    if locs:
        log_event(request, "individual_location_attach", {"employee_id": employee_id, "location_ids": location_ids})
    return {"ok": True}


@app.post("/vhr/hrm/division_list/{division_id}/attach_all_to_location")
def division_attach_all_to_location(request: Request, division_id: str, location_id: str = Form("")):
    """Перетаскивание ВСЕГО подразделения на локацию (см. запрос Vladimir:
    "зажать кнопку на самом подразделении... прикрепить все подразделение
    к локации") — прикрепляет к этой локации КАЖДОГО сотрудника, у кого
    division_id совпадает (только прямые сотрудники этого подразделения,
    не рекурсивно по дочерним подразделениям — осознанное упрощение).

    Это не только разовое действие — записывает ПОСТОЯННОЕ правило в
    division_locations (см. models.py): дальше employee_create() сам
    прикрепит эту локацию любому НОВОМУ сотруднику, заведённому в это
    подразделение, без повторного перетаскивания (фидбек: "новый
    сотрудник должен прикрепиться автоматически")."""
    db = request.state.db
    org = request.state.org
    loc = db.query(Location).filter_by(id=location_id, organization_id=org.id).first()
    if not loc:
        return {"ok": False, "error": "Локация не найдена"}
    employees = db.query(Employee).filter_by(organization_id=org.id, division_id=division_id).all()
    if not employees:
        return {"ok": False, "error": "В этом подразделении пока нет сотрудников"}
    for emp in employees:
        if loc not in emp.locations:
            emp.locations.append(loc)

    exists = db.execute(
        division_locations.select().where(
            division_locations.c.division_id == division_id,
            division_locations.c.location_id == location_id,
        )
    ).first()
    if not exists:
        db.execute(division_locations.insert().values(division_id=division_id, location_id=location_id))

    db.commit()
    log_event(request, "division_location_attach", {"division_id": division_id, "location_id": location_id})
    return {"ok": True, "count": len(employees)}


@app.post("/vhr/hrm/division_list/{division_id}/detach_location")
def division_detach_location(request: Request, division_id: str, location_id: str = Form("")):
    """Открепление подразделения от локации (по запросу Vladimir — "на
    случай, если что-то прикрепили ошибочно"). Симметрично attach:
    убирает ПРАВИЛО из division_locations И каскадом снимает эту
    локацию со ВСЕХ прямых сотрудников этого подразделения (не только
    у новых — у уже существующих тоже, иначе правило исчезло бы, а
    фактические привязки остались бы висеть)."""
    db = request.state.db
    org = request.state.org
    loc = db.query(Location).filter_by(id=location_id, organization_id=org.id).first()
    if not loc:
        return {"ok": False, "error": "Локация не найдена"}

    db.execute(
        division_locations.delete().where(
            division_locations.c.division_id == division_id,
            division_locations.c.location_id == location_id,
        )
    )
    employees = db.query(Employee).filter_by(organization_id=org.id, division_id=division_id).all()
    for emp in employees:
        if loc in emp.locations:
            emp.locations.remove(loc)
    db.commit()
    return {"ok": True, "count": len(employees)}


@app.post("/vhr/company/attach_all_to_location")
def company_attach_all_to_location(request: Request, location_id: str = Form("")):
    """CPO-фидбек: "добавить опцию прикрепления всей компании к выбранной
    локации" — тот же жест, что и у подразделения, только источник —
    корневой узел дерева (см. base.html). В ОТЛИЧИЕ от подразделения —
    это разовое действие, НЕ постоянное правило: новый сотрудник, заведённый
    после этого в ЛЮБОЕ подразделение, автоматически сюда не попадёт (кроме
    случая, когда для его конкретного подразделения отдельно установлено
    правило через attach_all_to_location). Осознанное упрощение — правило
    "вся компания" затрагивало бы вообще всех сотрудников независимо от
    подразделения, что плохо сочетается с моделью правил на уровне
    подразделения; если понадобится симметрично — обсудим отдельно."""
    db = request.state.db
    org = request.state.org
    loc = db.query(Location).filter_by(id=location_id, organization_id=org.id).first()
    if not loc:
        return {"ok": False, "error": "Локация не найдена"}
    employees = db.query(Employee).filter_by(organization_id=org.id).all()
    if not employees:
        return {"ok": False, "error": "В компании пока нет сотрудников"}
    for emp in employees:
        if loc not in emp.locations:
            emp.locations.append(loc)
    db.commit()
    log_event(request, "individual_location_attach", {"scope": "company", "location_id": location_id})
    return {"ok": True, "count": len(employees)}


# ============================================================
# Пользователи (Настройки → Администрирование → Пользователи) — инвайт
#
# В реальном Verifix это отдельная сущность (системный доступ), но для
# мока привязываем инвайт прямо к записи сотрудника — иначе пришлось бы
# вводить полноценную модель User/Employee связи, а для двух наших JTBD
# важна только связка "у сотрудника есть активированное приложение".
# ============================================================

@app.get("/vhr/admin/users")
def users_list(request: Request):
    db = request.state.db
    org = request.state.org
    employees = db.query(Employee).filter_by(organization_id=org.id).all()
    log_event(request, "page_view")
    ctx = base_ctx(request, "page.users")
    ctx.update(employees=employees)
    return templates.TemplateResponse(request, "users_list.html", ctx)


@app.post("/vhr/admin/users/{employee_id}/invite")
def users_invite(request: Request, employee_id: str, phone: str = Form("")):
    if not phone.strip():
        return redirect_with_error("/vhr/admin/users", t('err.user_phone_empty'))
    db = request.state.db
    org = request.state.org
    emp = db.query(Employee).filter_by(id=employee_id, organization_id=org.id).first()
    if emp:
        emp.phone = phone.strip()
        emp.invite_status = "invited"
        emp.invited_at = datetime.now(timezone.utc)
        db.commit()
        log_event(request, "invite_sent", {"employee_id": employee_id})
    return RedirectResponse(url="/vhr/admin/users", status_code=303)


@app.post("/vhr/admin/users/{employee_id}/simulate_activate")
def users_simulate_activate(request: Request, employee_id: str):
    """Оставлено как ЭНДПОИНТ (не удаляю совсем — старые данные могли
    сослаться на activated_at), но кнопка убрана из UI (см. users_list.html)
    — концепт больше не должен требовать симулировать ПРИНЯТИЕ приглашения,
    только его отправку (см. изменение has_uninvited_employees выше)."""
    db = request.state.db
    org = request.state.org
    emp = db.query(Employee).filter_by(id=employee_id, organization_id=org.id).first()
    if emp and emp.invite_status == "invited":
        emp.invite_status = "active"
        emp.activated_at = datetime.now(timezone.utc)
        db.commit()
        log_event(request, "invite_activated", {"employee_id": employee_id})
    return RedirectResponse(url="/vhr/admin/users", status_code=303)


# ============================================================
# Отметки (htt) — JTBD №1
# ============================================================

@app.get("/vhr/htt/attendance_mark")
def attendance_mark_page(request: Request):
    db = request.state.db
    org = request.state.org
    all_employees = db.query(Employee).filter_by(organization_id=org.id).all()
    locations = db.query(Location).filter_by(organization_id=org.id).all()
    events = (
        db.query(AttendanceEvent)
        .filter_by(organization_id=org.id)
        .order_by(AttendanceEvent.marked_at.desc())
        .limit(200)
        .all()
    )
    log_event(request, "page_view")
    ctx = base_ctx(request, "page.attendance")
    # По запросу Vladimir (со скринами реального Verifix): убрана форма
    # ручного создания отметки — в реальном Verifix эта страница ЧИСТО
    # просмотровая (отметки приходят от устройств/приложения, не через
    # ручную форму в админке). Показываем РЕАЛЬНЫЕ данные из БД (могут
    # быть пустыми) — никаких выдуманных строк. Панель оргструктуры
    # справа скрыта — вкладка должна быть на весь экран, как в референсе.
    ctx.update(all_employees=all_employees, locations=locations, events=events, hide_org_panel=True)
    return templates.TemplateResponse(request, "attendance_mark.html", ctx)


# ============================================================
# Отчёт по часам (htt) — JTBD №2
# ============================================================

@app.get("/vhr/htt/timesheet_report")
def timesheet_report(request: Request):
    db = request.state.db
    org = request.state.org
    employees = db.query(Employee).filter_by(organization_id=org.id).all()
    divisions = db.query(Division).filter_by(organization_id=org.id).all()
    schedules = db.query(Schedule).filter_by(organization_id=org.id).all()
    events = (
        db.query(AttendanceEvent)
        .filter_by(organization_id=org.id)
        .order_by(AttendanceEvent.marked_at.asc())
        .all()
    )

    schedule_by_id = {s.id: s for s in schedules}

    # По референсу реального Verifix — календарная сетка по дням месяца,
    # не список пар приход/уход. Период: с 1 числа текущего месяца по
    # сегодня (то же самое, что показано на скрине "01 авг - 17 авг").
    today_local = to_local(datetime.now(timezone.utc)).date()
    period_start = today_local.replace(day=1)
    period_days = [period_start + timedelta(days=i) for i in range((today_local - period_start).days + 1)]

    # Группируем реальные отметки по (сотрудник, локальная календарная дата).
    events_by_emp_day = defaultdict(list)
    for ev in events:
        d = to_local(ev.marked_at).date()
        events_by_emp_day[(ev.employee_id, d)].append(ev)

    def hours_for_day(evs):
        pending_in = None
        total = 0.0
        for ev in sorted(evs, key=lambda e: e.marked_at):
            if ev.kind == "in":
                pending_in = ev
            elif ev.kind == "out" and pending_in:
                total += (ev.marked_at - pending_in.marked_at).total_seconds() / 3600
                pending_in = None
        return round(total, 2) if total else None

    rows = []
    for emp in employees:
        sched = schedule_by_id.get(emp.schedule_id)
        week_days = set(sched.week_days or []) if sched else set()
        day_cells = []
        total_hours = 0.0
        for d in period_days:
            # Schedule.week_days: 1=Пн..7=Вс — ровно как date.isoweekday(), без конвертации.
            is_workday = d.isoweekday() in week_days
            hours = hours_for_day(events_by_emp_day.get((emp.id, d), []))
            if hours:
                total_hours += hours
            day_cells.append({"day": d.day, "is_workday": is_workday, "hours": hours})
        rows.append({
            "employee": emp,
            "division_name": name_by_id(divisions, emp.division_id),
            "days": day_cells,
            "total_hours": round(total_hours, 2) if total_hours else 0,
        })

    log_event(request, "page_view")
    ctx = base_ctx(request, "page.report")
    # Тоже реальные данные, тоже во весь экран (см. attendance_mark_page).
    ctx.update(rows=rows, period_days=period_days, period_start=period_start, period_end=today_local, hide_org_panel=True)
    return templates.TemplateResponse(request, "timesheet_report.html", ctx)


# ============================================================
# Stub-страницы — регистрируются из menu.py, чтобы пункты меню и
# реальные роуты никогда не расходились.
# ============================================================

def _make_stub_handler(path: str, label: str, module_label: str):
    def handler(request: Request):
        log_event(request, "page_view")
        ctx = base_ctx(request, label)
        ctx.update(label=label, module_label=module_label)
        return templates.TemplateResponse(request, "stub.html", ctx)
    return handler


for _path, _label, _module_label in all_stub_paths():
    app.get(_path)(_make_stub_handler(_path, _label, _module_label))


# ============================================================
# Статика
# ============================================================

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

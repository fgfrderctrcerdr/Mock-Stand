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
from datetime import datetime, timedelta, timezone
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
)

from contextlib import asynccontextmanager

BASE_DIR = Path(__file__).parent

# Портировано из старого standalone-концепта (web_onboarding/static/i18n.js,
# app.js) по просьбе Vladimir после пилотного теста с CPO — тексты и набор
# сфер/ролей там уже проверены, не придумываю заново.

INDUSTRIES = [
    ("retail", "Розница и торговля"),
    ("food", "Общепит и HoReCa"),
    ("it", "IT и услуги"),
    ("manuf", "Производство"),
    ("edu", "Образование"),
    ("health", "Медицина"),
    ("other", "Другое"),
]

ADMIN_ROLES = [
    ("owner", "Владелец бизнеса"),
    ("hr", "HR-менеджер"),
    ("lead", "Руководитель отдела"),
    ("fin", "Бухгалтер / финансы"),
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


class OrgSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # QA M1: раньше создавало Organization на ЛЮБОЙ запрос без cookie —
        # включая /static/*, /favicon.ico и т.п. Любой бот/скан/битая ссылка
        # плодит мусорные организации в БД, ничего не настраивая. Эти пути
        # не читают request.state.org/db вообще, пропускаем без сессии.
        path = request.url.path
        if path.startswith("/static/") or path == "/favicon.ico":
            return await call_next(request)

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
        try:
            response = await call_next(request)
        finally:
            db.close()

        if created:
            response.set_cookie(COOKIE_NAME, org_token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365)
        return response


app.add_middleware(OrgSessionMiddleware)


# На время активной разработки — без этого браузер может закешировать
# JS/CSS (особенно static/tour/*) агрессивнее, чем HTML, и после git pull
# показывать старую версию тура даже после обычного рефреша страницы.
@app.middleware("http")
async def disable_static_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
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

    emp_by_division = defaultdict(list)
    emp_by_location = defaultdict(list)
    for e in employees:
        if e.division_id:
            emp_by_division[e.division_id].append(e)
        if e.location_id:
            emp_by_location[e.location_id].append(e)

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

    loc_rows = [
        {"location": l, "employees": emp_by_location.get(l.id, [])}
        for l in locations
    ]
    unassigned = [e for e in employees if not e.location_id]

    return {
        "division_tree": division_tree,
        "company_name": org.company_name,
        "loc_rows": loc_rows,
        "unassigned": unassigned,
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
    подразделения в стиле реального Verifix (см. референс-скриншот)."""
    n_abs = abs(n) % 100
    n1 = n_abs % 10
    if 11 <= n_abs <= 14:
        return "сотрудников"
    if n1 == 1:
        return "сотрудник"
    if 2 <= n1 <= 4:
        return "сотрудника"
    return "сотрудников"


def base_ctx(request: Request, page_title: str):
    current_section = None
    for section in MENU:
        for col in section["columns"]:
            for path, _, _ in col["links"]:
                if path == request.url.path:
                    current_section = section["label"]
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
    ctx = base_ctx(request, "Главная")
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
        return redirect_with_error("/", "Название компании не может быть пустым.")
    if industry not in dict(INDUSTRIES):
        return redirect_with_error("/", "Выберите сферу деятельности из списка.")
    if admin_role not in dict(ADMIN_ROLES):
        return redirect_with_error("/", "Выберите, кем вы являетесь в компании.")

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
    ctx = base_ctx(request, "Подразделения")
    ctx.update(
        divisions=divisions,
        ordered=_ordered_divisions(divisions),
        suggestions=suggestions,
    )
    return templates.TemplateResponse(request, "division_list.html", ctx)


@app.post("/vhr/hrm/division_list/create")
def division_create(request: Request, name: str = Form(""), parent_id: str = Form("")):
    if not name.strip():
        return redirect_with_error("/vhr/hrm/division_list", "Название подразделения не может быть пустым.")
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
    ctx = base_ctx(request, "Должности")
    ctx.update(positions=positions, suggestions=suggestions)
    return templates.TemplateResponse(request, "job_list.html", ctx)


@app.post("/vhr/hrm/job_list/create")
def job_create(request: Request, name: str = Form("")):
    if not name.strip():
        return redirect_with_error("/vhr/hrm/job_list", "Название должности не может быть пустым.")
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
    ctx = base_ctx(request, "Локации")
    ctx.update(locations=locations)
    return templates.TemplateResponse(request, "location_list.html", ctx)


@app.post("/vhr/htt/location_list/create")
def location_create(request: Request, name: str = Form(""), lat: str = Form(""), lng: str = Form(""), accuracy: str = Form("50"), address: str = Form("")):
    if not name.strip():
        return redirect_with_error("/vhr/htt/location_list", "Название локации не может быть пустым.")
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
            "Не удалось определить координаты — карта могла не успеть загрузиться. Кликните точку на карте или найдите адрес заново."
        )
    # QA L1: accuracy тоже был типизирован как float = Form(50) — тот же
    # класс проблемы (сырой 422 на нечисловом крафте), а не просто "min=1".
    try:
        accuracy_val = float(accuracy)
    except ValueError:
        return redirect_with_error("/vhr/htt/location_list", "Радиус зоны отметок должен быть числом.")
    if accuracy_val <= 0:
        return redirect_with_error("/vhr/htt/location_list", "Радиус зоны отметок должен быть больше нуля.")
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
    # прикреплённый к удаляемой локации пропадает из панели ПОЛНОСТЬЮ —
    # не в кружке (локации нет), не в пуле "не прикреплены" (location_id
    # не None, а мёртвый id) — и вернуть его через DnD уже нельзя.
    db.query(Employee).filter_by(organization_id=org.id, location_id=location_id).update({"location_id": None})
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
    ctx = base_ctx(request, "Графики работы")
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
        return redirect_with_error("/vhr/htt/schedule_list", "Название графика не может быть пустым.")
    if kind not in ("regular", "hourly"):
        return redirect_with_error("/vhr/htt/schedule_list", "Неизвестный вид графика.")

    if kind == "regular":
        if not week_days:
            return redirect_with_error("/vhr/htt/schedule_list", "У обычного графика должен быть хотя бы один рабочий день.")
        # QA L1: int(d) без защиты падал в 500 на нечисловом крафте, и не было
        # проверки диапазона 1–7 (дни недели) — валидный HTML-чекбокс всегда
        # шлёт "1".."7", но эндпоинт не должен ронять сервер на произвольном вводе.
        try:
            week_days_int = sorted(set(int(d) for d in week_days))
        except ValueError:
            return redirect_with_error("/vhr/htt/schedule_list", "Некорректный день недели.")
        if any(d < 1 or d > 7 for d in week_days_int):
            return redirect_with_error("/vhr/htt/schedule_list", "День недели должен быть от 1 (понедельник) до 7 (воскресенье).")
        if not start_time or not end_time:
            return redirect_with_error("/vhr/htt/schedule_list", "Укажите начало и конец рабочего дня.")
        if start_time >= end_time:
            return redirect_with_error("/vhr/htt/schedule_list", "Конец рабочего дня должен быть позже начала (ночные смены через полночь — отдельный случай, здесь не поддержан).")

    if kind == "hourly":
        try:
            norm_val = float(norm_hours)
        except ValueError:
            norm_val = 0
        if norm_val <= 0:
            return redirect_with_error("/vhr/htt/schedule_list", "Норма часов должна быть больше нуля.")

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
    ctx = base_ctx(request, "Сотрудники")
    ctx.update(employees=employees, divisions=divisions, positions=positions, schedules=schedules, locations=locations)
    return templates.TemplateResponse(request, "employee_list.html", ctx)


@app.post("/vhr/href/employee/create")
def employee_create(
    request: Request,
    full_name: str = Form(""),
    division_id: str = Form(""),
    position_id: str = Form(""),
    schedule_id: str = Form(""),
    location_id: str = Form(""),
):
    # QA-фикс №10 (первая версия) требовал ВСЕ 4 связи при создании,
    # включая локацию. Теперь это пересмотрено: появилась постоянная
    # панель справа с drag-and-drop прикреплением сотрудника к локации
    # (см. запрос Vladimir после пилота с CPO) — сотрудник должен мочь
    # существовать «непривязанным» (в пуле unassigned), чтобы это
    # прикрепление имело смысл как отдельное действие. Локация теперь
    # необязательна при создании; подразделение/должность/график —
    # остаются обязательными (для них альтернативного способа задать
    # значение после создания нет).
    if not full_name.strip():
        return redirect_with_error("/vhr/href/employee", "ФИО сотрудника не может быть пустым.")
    if not (division_id and position_id and schedule_id):
        return redirect_with_error(
            "/vhr/href/employee",
            "Заполните подразделение, должность и график. Локацию можно прикрепить позже — перетащите сотрудника на неё в панели справа."
        )
    db = request.state.db
    org = request.state.org
    e = Employee(
        organization_id=org.id,
        full_name=full_name.strip(),
        division_id=division_id or None,
        position_id=position_id or None,
        schedule_id=schedule_id or None,
        location_id=location_id or None,
    )
    db.add(e)
    db.commit()
    log_event(request, "entity_created", {"entity": "employee", "id": e.id})
    return RedirectResponse(url="/vhr/href/employee", status_code=303)


@app.post("/vhr/href/employee/{employee_id}/delete")
def employee_delete(request: Request, employee_id: str):
    db = request.state.db
    org = request.state.org
    # QA M6: без этого отметки удалённого сотрудника остаются висячими —
    # в списке отметок и в отчёте по часам имя рендерится как "—" (name_by_id
    # не находит сотрудника в текущем списке).
    db.query(AttendanceEvent).filter_by(organization_id=org.id, employee_id=employee_id).delete()
    db.query(Employee).filter_by(id=employee_id, organization_id=org.id).delete()
    db.commit()
    return RedirectResponse(url="/vhr/href/employee", status_code=303)


@app.post("/vhr/href/employee/{employee_id}/assign_location")
def employee_assign_location(request: Request, employee_id: str, location_id: str = Form("")):
    """Drag-and-drop сотрудника на локацию в постоянной панели справа
    (см. запрос Vladimir после пилота) — тот же location_id, что и
    выпадающий список в форме сотрудника, просто другой способ задать
    его. AJAX, не редирект — панель сама перерисуется на клиенте."""
    db = request.state.db
    org = request.state.org
    emp = db.query(Employee).filter_by(id=employee_id, organization_id=org.id).first()
    if not emp:
        return {"ok": False, "error": "Сотрудник не найден"}
    loc_id = location_id or None
    if loc_id:
        loc = db.query(Location).filter_by(id=loc_id, organization_id=org.id).first()
        if not loc:
            return {"ok": False, "error": "Локация не найдена"}
    emp.location_id = loc_id
    db.commit()
    return {"ok": True}


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
    ctx = base_ctx(request, "Пользователи")
    ctx.update(employees=employees)
    return templates.TemplateResponse(request, "users_list.html", ctx)


@app.post("/vhr/admin/users/{employee_id}/invite")
def users_invite(request: Request, employee_id: str, phone: str = Form("")):
    if not phone.strip():
        return redirect_with_error("/vhr/admin/users", "Номер телефона не может быть пустым.")
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
    """Кнопка-эмулятор: 'сотрудник поставил Verifix ID и принял инвайт'.
    Настоящий мобильный флоу (SMS → установка → deep link) — открытый
    вопрос по дизайну, см. обсуждение с Vladimir; для мока схлопываем
    в один клик, чтобы можно было дойти до JTBD-1/2."""
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
    active_employees = db.query(Employee).filter_by(organization_id=org.id, invite_status="active").all()
    all_employees = db.query(Employee).filter_by(organization_id=org.id).all()
    events = (
        db.query(AttendanceEvent)
        .filter_by(organization_id=org.id)
        .order_by(AttendanceEvent.marked_at.desc())
        .limit(20)
        .all()
    )
    log_event(request, "page_view")
    ctx = base_ctx(request, "Отметки")
    # QA-находка попутно: раньше в таблице "последние отметки" имя искалось
    # только среди АКТИВНЫХ сотрудников (employees) — если сотрудник успел
    # деактивироваться, но не удалиться, его старые отметки показывали "—"
    # хотя сотрудник по факту существует. Для списка/выбора — активные;
    # для отображения имени в истории — все.
    ctx.update(employees=active_employees, all_employees=all_employees, events=events, has_any_employee=bool(all_employees))
    return templates.TemplateResponse(request, "attendance_mark.html", ctx)


@app.post("/vhr/htt/attendance_mark/create")
def attendance_mark_create(request: Request, employee_id: str = Form(""), kind: str = Form("in"), hours_ago: str = Form("0")):
    # QA M2: раньше строило AttendanceEvent с сырым employee_id независимо
    # от того, найден ли сотрудник и активен ли он, и не ограничивало kind.
    if kind not in ("in", "out"):
        return redirect_with_error("/vhr/htt/attendance_mark", "Некорректный тип отметки.")
    db = request.state.db
    org = request.state.org
    emp = db.query(Employee).filter_by(id=employee_id, organization_id=org.id, invite_status="active").first()
    if not emp:
        return redirect_with_error("/vhr/htt/attendance_mark", "Сотрудник не найден или ещё не активирован — выберите из списка.")

    # QA M3: раньше приход и уход всегда писались "прямо сейчас" — при
    # демонстрации кликаешь оба подряд, разница уходит в округление до 0.00ч,
    # и кульминационный отчёт показывает 0 часов. Позволяем "задним числом"
    # отметить приход на N часов назад, чтобы уход "сейчас" давал реалистичную
    # разницу.
    try:
        h = max(0.0, min(48.0, float(hours_ago)))
    except ValueError:
        h = 0.0
    marked_at = datetime.now(timezone.utc) - timedelta(hours=h)

    ev = AttendanceEvent(
        organization_id=org.id,
        employee_id=employee_id,
        location_id=emp.location_id,
        kind=kind,
        marked_at=marked_at,
    )
    db.add(ev)
    db.commit()
    log_event(request, "attendance_marked", {"employee_id": employee_id, "kind": kind, "hours_ago": h})
    return RedirectResponse(url="/vhr/htt/attendance_mark", status_code=303)


# ============================================================
# Отчёт по часам (htt) — JTBD №2
# ============================================================

@app.get("/vhr/htt/timesheet_report")
def timesheet_report(request: Request):
    db = request.state.db
    org = request.state.org
    employees = db.query(Employee).filter_by(organization_id=org.id).all()
    events = (
        db.query(AttendanceEvent)
        .filter_by(organization_id=org.id)
        .order_by(AttendanceEvent.marked_at.asc())
        .all()
    )

    by_employee = defaultdict(list)
    for ev in events:
        by_employee[ev.employee_id].append(ev)

    rows = []
    for emp_id, evs in by_employee.items():
        # Простое попарное сведение in→out по порядку — для мока достаточно,
        # реальный расчёт с ночными сменами/пропусками — задача hpr, не мока.
        pending_in = None
        for ev in evs:
            if ev.kind == "in":
                pending_in = ev
            elif ev.kind == "out" and pending_in:
                hours = round((ev.marked_at - pending_in.marked_at).total_seconds() / 3600, 2)
                rows.append({
                    "id": pending_in.id + "_" + ev.id,
                    "employee_name": name_by_id(employees, emp_id),
                    "in_at": pending_in.marked_at,
                    "out_at": ev.marked_at,
                    "hours": hours,
                })
                pending_in = None
        if pending_in:
            rows.append({
                "id": pending_in.id,
                "employee_name": name_by_id(employees, emp_id),
                "in_at": pending_in.marked_at,
                "out_at": None,
                "hours": None,
            })

    log_event(request, "page_view")
    ctx = base_ctx(request, "Отчёт по часам")
    ctx.update(rows=rows)
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

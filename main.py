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
from datetime import datetime, timezone
from pathlib import Path

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

BASE_DIR = Path(__file__).parent
app = FastAPI(title="Verifix Mock-Stand")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def name_by_id(items, item_id):
    for it in items:
        if it.id == item_id:
            return it.name if hasattr(it, "name") else it.full_name
    return "—"


templates.env.globals["name_by_id"] = name_by_id


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


# ============================================================
# Org-сессия по cookie (см. docstring выше)
# ============================================================

COOKIE_NAME = "mock_org"


class OrgSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
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


def log_event(request: Request, type_: str, meta: dict | None = None):
    db = request.state.db
    db.add(TelemetryEvent(organization_id=request.state.org.id, type=type_, path=request.url.path, meta=meta or {}))
    db.commit()


def base_ctx(request: Request, page_title: str):
    current_section = None
    for section in MENU:
        for path, _, _ in section["links"]:
            if path == request.url.path:
                current_section = section["label"]
    return {
        "request": request,
        "page_title": page_title,
        "menu": MENU,
        "current_path": request.url.path,
        "current_section": current_section,
        "org_id": request.state.org.id,
    }


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
    ctx = base_ctx(request, "Главная")
    return templates.TemplateResponse(request, "home.html", ctx)


# ============================================================
# Подразделения (hrm)
# ============================================================

def _ordered_divisions(divisions):
    """DFS с сохранением глубины — для дерева с отступами (см. web_onboarding app.js)."""
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
    log_event(request, "page_view")
    ctx = base_ctx(request, "Подразделения")
    ctx.update(
        divisions=divisions,
        ordered=_ordered_divisions(divisions),
        parent_name=lambda pid: name_by_id(divisions, pid) if pid else "верхний уровень",
    )
    return templates.TemplateResponse(request, "division_list.html", ctx)


@app.post("/vhr/hrm/division_list/create")
def division_create(request: Request, name: str = Form(...), parent_id: str = Form("")):
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
    log_event(request, "page_view")
    ctx = base_ctx(request, "Должности")
    ctx.update(positions=positions)
    return templates.TemplateResponse(request, "job_list.html", ctx)


@app.post("/vhr/hrm/job_list/create")
def job_create(request: Request, name: str = Form(...)):
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
def location_create(request: Request, name: str = Form(...), lat: float = Form(...), lng: float = Form(...), accuracy: float = Form(50), address: str = Form("")):
    db = request.state.db
    org = request.state.org
    l = Location(organization_id=org.id, name=name.strip(), address=address, lat=lat, lng=lng, accuracy=accuracy)
    db.add(l)
    db.commit()
    log_event(request, "entity_created", {"entity": "location", "id": l.id})
    return RedirectResponse(url="/vhr/htt/location_list", status_code=303)


@app.post("/vhr/htt/location_list/{location_id}/delete")
def location_delete(request: Request, location_id: str):
    db = request.state.db
    org = request.state.org
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
    name: str = Form(...),
    kind: str = Form("regular"),
    week_days: list[str] = Form([]),
    start_time: str = Form(""),
    end_time: str = Form(""),
    norm_hours: str = Form(""),
):
    db = request.state.db
    org = request.state.org
    s = Schedule(
        organization_id=org.id,
        name=name.strip(),
        kind=kind,
        week_days=[int(d) for d in week_days] if kind == "regular" else [],
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
    full_name: str = Form(...),
    division_id: str = Form(""),
    position_id: str = Form(""),
    schedule_id: str = Form(""),
    location_id: str = Form(""),
):
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
    db.query(Employee).filter_by(id=employee_id, organization_id=org.id).delete()
    db.commit()
    return RedirectResponse(url="/vhr/href/employee", status_code=303)


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
def users_invite(request: Request, employee_id: str, phone: str = Form(...)):
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
    employees = db.query(Employee).filter_by(organization_id=org.id, invite_status="active").all()
    all_employees_count = db.query(Employee).filter_by(organization_id=org.id).count()
    events = (
        db.query(AttendanceEvent)
        .filter_by(organization_id=org.id)
        .order_by(AttendanceEvent.marked_at.desc())
        .limit(20)
        .all()
    )
    log_event(request, "page_view")
    ctx = base_ctx(request, "Отметки")
    ctx.update(employees=employees, events=events, has_any_employee=all_employees_count > 0)
    return templates.TemplateResponse(request, "attendance_mark.html", ctx)


@app.post("/vhr/htt/attendance_mark/create")
def attendance_mark_create(request: Request, employee_id: str = Form(...), kind: str = Form("in")):
    db = request.state.db
    org = request.state.org
    emp = db.query(Employee).filter_by(id=employee_id, organization_id=org.id).first()
    ev = AttendanceEvent(
        organization_id=org.id,
        employee_id=employee_id,
        location_id=emp.location_id if emp else None,
        kind=kind,
    )
    db.add(ev)
    db.commit()
    log_event(request, "attendance_marked", {"employee_id": employee_id, "kind": kind})
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

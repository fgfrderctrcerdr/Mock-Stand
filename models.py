"""
Модели БД для Mock-Stand.

Organization здесь — не клиент SaaS (как в web_onboarding), а просто
изолированная "песочница": один браузер = один cookie = одна
Organization = свой набор подразделений/сотрудников. Так несколько
человек могут одновременно проходить мок независимо, не путая данные.

AttendanceEvent — симуляция отметки (раз нет настоящего мобильного
трекера): кнопка "Отметиться" на /vhr/htt/attendance_mark создаёт
событие in/out, а /vhr/htt/attendance_report считает из пар in→out
отработанные часы. Это и есть JTBD-2.
"""

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, String, Table
from sqlalchemy.orm import relationship

from db import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def gen_token() -> str:
    return secrets.token_urlsafe(24)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=gen_uuid)
    token = Column(String, unique=True, index=True, default=gen_token)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Профиль компании — портировано с первого шага старого концепта
    # (web_onboarding, "welcome → role → needs → company"), см. запрос
    # Vladimir после пилотного теста. industry управляет типовыми
    # подсказками подразделений/должностей (см. menu.py DIVISION_/
    # POSITION_SUGGESTIONS в main.py).
    company_name = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    admin_role = Column(String, nullable=True)

    divisions = relationship("Division", back_populates="organization", cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="organization", cascade="all, delete-orphan")
    schedules = relationship("Schedule", back_populates="organization", cascade="all, delete-orphan")
    locations = relationship("Location", back_populates="organization", cascade="all, delete-orphan")
    employees = relationship("Employee", back_populates="organization", cascade="all, delete-orphan")


class Division(Base):
    __tablename__ = "divisions"
    id = Column(String, primary_key=True, default=gen_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    parent_id = Column(String, ForeignKey("divisions.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    organization = relationship("Organization", back_populates="divisions")


class Position(Base):
    __tablename__ = "positions"
    id = Column(String, primary_key=True, default=gen_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    organization = relationship("Organization", back_populates="positions")


class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(String, primary_key=True, default=gen_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    kind = Column(String, default="regular")  # regular | hourly
    week_days = Column(JSON, default=list)    # [1..7] (пн=1) — только для kind='regular'
    start_time = Column(String, nullable=True)  # только для kind='regular'
    end_time = Column(String, nullable=True)     # только для kind='regular'
    norm_hours = Column(Float, nullable=True)    # только для kind='hourly'
    created_at = Column(DateTime(timezone=True), default=utcnow)

    organization = relationship("Organization", back_populates="schedules")


class Location(Base):
    __tablename__ = "locations"
    id = Column(String, primary_key=True, default=gen_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    address = Column(String, default="")
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    accuracy = Column(Float, default=50)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    organization = relationship("Organization", back_populates="locations")


# Постоянное ПРАВИЛО «подразделение прикреплено к локации» — отдельно от
# фактических привязок сотрудников (employee_locations). Фидбек Vladimir:
# "прикрепление подразделения к локации" раньше было разовым действием —
# добавляло текущих сотрудников, но НОВЫЙ сотрудник, заведённый в это
# подразделение позже, не получал локацию автоматически. Теперь это
# правило, а не разовая операция: см. employee_create() — при создании
# сотрудника с division_id читаем отсюда все локации ЭТОГО подразделения
# и сразу прикрепляем их сотруднику тоже.
division_locations = Table(
    "division_locations",
    Base.metadata,
    Column("division_id", String, ForeignKey("divisions.id"), primary_key=True),
    Column("location_id", String, ForeignKey("locations.id"), primary_key=True),
)


class Employee(Base):
    __tablename__ = "employees"
    id = Column(String, primary_key=True, default=gen_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    full_name = Column(String, nullable=False)
    division_id = Column(String, ForeignKey("divisions.id"), nullable=True)
    position_id = Column(String, ForeignKey("positions.id"), nullable=True)
    schedule_id = Column(String, ForeignKey("schedules.id"), nullable=True)
    # QA-фидбек Vladimir: "1 человек может быть прикреплён к нескольким
    # локациям" — было Column(ForeignKey) один-к-одному, теперь
    # многие-ко-многим через employee_locations (см. ниже). Колонку
    # location_id убрал совсем — единственный способ задать локацию
    # теперь через таблицу employee_locations (drag-and-drop в панели
    # или мультиселект в employee_list.html).
    locations = relationship("Location", secondary="employee_locations", backref="employees")

    # Инвайт в приложение (по мотивам реального экрана Настройки → Пользователи →
    # тумблер "Телефон + invite"): none → invited (эмулируем отправку SMS) →
    # active (эмулируем, что сотрудник поставил приложение и принял инвайт).
    phone = Column(String, nullable=True)
    invite_status = Column(String, default="none")  # none | invited | active
    invited_at = Column(DateTime(timezone=True), nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    organization = relationship("Organization", back_populates="employees")


# Ассоциативная таблица «сотрудник ↔ локация» (многие-ко-многим). Без
# отдельной ORM-модели — просто Table, как рекомендует SQLAlchemy для
# чистых many-to-many без дополнительных полей на связи.
employee_locations = Table(
    "employee_locations",
    Base.metadata,
    Column("employee_id", String, ForeignKey("employees.id"), primary_key=True),
    Column("location_id", String, ForeignKey("locations.id"), primary_key=True),
)


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"
    id = Column(String, primary_key=True, default=gen_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    employee_id = Column(String, ForeignKey("employees.id"), nullable=False, index=True)
    # Это НЕ "назначенная" локация сотрудника (той больше нет как единственной
    # ссылки, см. Employee.locations выше) — это то, где КОНКРЕТНО произошла
    # ЭТА отметка (одна из локаций сотрудника на момент отметки).
    location_id = Column(String, ForeignKey("locations.id"), nullable=True)
    kind = Column(String, nullable=False)  # "in" | "out"
    marked_at = Column(DateTime(timezone=True), default=utcnow)


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"
    id = Column(String, primary_key=True, default=gen_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    type = Column(String, nullable=False)     # page_view | entity_created | attendance_marked
    path = Column(String, nullable=True)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)

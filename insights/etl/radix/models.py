"""
Pydantic models for Radix RxPlusService API responses.

Ported from KRAI (`backend/pm/models/radix_models.py`) and upgraded to Pydantic
v2 `model_config` (the KRAI version used the deprecated inner `class Config`).
Maps Radix activity / spare part / work time data structures.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RadixActivity(BaseModel):
    """Radix service activity (ticket equivalent)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., alias="id")
    customer_id: str | None = Field(None, alias="customerId")
    customer_name: str | None = Field(None, alias="customerName")
    device_model: str | None = Field(None, alias="deviceModel")
    device_serial: str | None = Field(None, alias="deviceSerial")
    problem_description: str | None = Field(None, alias="problemDescription")
    problem_short: str | None = Field(None, alias="problemShort")
    state: str | None = Field(None, alias="state")
    activity_type: str | None = Field(None, alias="activityType")
    created_date: datetime | None = Field(None, alias="createdDate")
    modified_date: datetime | None = Field(None, alias="modifiedDate")
    scheduled_date: datetime | None = Field(None, alias="scheduledDate")
    completed_date: datetime | None = Field(None, alias="completedDate")
    assigned_to: str | None = Field(None, alias="assignedTo")
    code: str | None = Field(None, alias="code")  # Location/branch code (e.g. "1FB")
    priority: int | None = Field(None, alias="priority")
    notes: str | None = Field(None, alias="notes")
    metadata: dict[str, Any] | None = Field(default_factory=dict, alias="metaData")


class RadixSparePart(BaseModel):
    """Radix spare part used in an activity."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., alias="id")
    activity_id: str | None = Field(None, alias="activityId")
    part_number: str | None = Field(None, alias="partNumber")
    part_name: str | None = Field(None, alias="partName")
    quantity: int | None = Field(None, alias="quantity")
    unit_price: float | None = Field(None, alias="unitPrice")
    total_price: float | None = Field(None, alias="totalPrice")
    used_date: datetime | None = Field(None, alias="usedDate")
    notes: str | None = Field(None, alias="notes")


class RadixWorkTime(BaseModel):
    """Radix work time entry (logged hours)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., alias="id")
    activity_id: str | None = Field(None, alias="activityId")
    employee_id: str | None = Field(None, alias="employeeId")
    employee_name: str | None = Field(None, alias="employeeName")
    start_time: datetime | None = Field(None, alias="startTime")
    end_time: datetime | None = Field(None, alias="endTime")
    duration_minutes: float | None = Field(None, alias="durationMinutes")
    work_type: str | None = Field(None, alias="workType")
    notes: str | None = Field(None, alias="notes")


class RadixActivityState(BaseModel):
    """Radix activity status code."""

    model_config = ConfigDict(populate_by_name=True)

    code: str | None = Field(None, alias="code")
    name: str | None = Field(None, alias="name")
    description: str | None = Field(None, alias="description")


class RadixActivityType(BaseModel):
    """Radix activity type code."""

    model_config = ConfigDict(populate_by_name=True)

    code: str | None = Field(None, alias="code")
    name: str | None = Field(None, alias="name")
    description: str | None = Field(None, alias="description")

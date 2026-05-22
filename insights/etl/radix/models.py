"""
Pydantic models for the Radix RxPlusService API (Infominds), API v26.12.0.

Rewritten 2026-05-22 against the LIVE API (OpenAPI `/swagger/v1/swagger.json`)
after the originally ported models proved wrong. Verified shapes against real
reads: serialnumber (+ details / counter / contracts), activity (+ time),
customer. Spare-part / spare-part-price payloads were not yet seen populated, so
those models are permissive (`extra="allow"`).

DATA PROTECTION (DSGVO): these models DELIBERATELY omit personal data — contact
person name/email/phone and employee names. Only a pseudonymous `employee_id` is
kept (for cost/labour attribution). With Pydantic's default `extra="ignore"`,
any PII present in the raw payload is dropped on validation and never reaches
the Insights DB. The two permissive models below carry only non-personal
material/price data.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _RadixModel(BaseModel):
    """Base: accept camelCase aliases, drop unknown (incl. PII) fields."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class RadixArticle(BaseModel):
    """Article master embedded in a serialnumber (model/producer/warranty)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str | None = None
    code: str | None = None
    searchtext: str | None = None
    model: str | None = None
    producer: str | None = None
    warranty_customer: str | None = Field(None, alias="warrantyCustomer")
    inactive: bool | None = None


class RadixCustomer(_RadixModel):
    """A Radix customer — company + location only (no contact persons / PII).

    The live payload also carries email/phone/fax/salutation/letterSalutation —
    all PII. With `extra="ignore"` and this explicit field whitelist, those are
    dropped on validation and never reach the Insights DB.
    """

    id: str = Field(..., alias="id")
    number: int | None = None
    description: str | None = None  # company name
    optional: str | None = None     # secondary name line (e.g. "Atelier für Gestaltung")
    legalform: str | None = None    # legal form, if maintained (helps normalisation)
    street: str | None = None       # location data (allowed)
    streetnumber: str | None = None
    zip: str | None = Field(None, alias="postalCode")
    town: str | None = None
    country: str | None = None
    address_id: str | None = Field(None, alias="addressId")
    inactive: bool | None = None
    # PII intentionally omitted: salutation, letterSalutation, email, phone, fax, contacts.


class RadixSerialNumber(_RadixModel):
    """A device in Radix.

    JOIN KEY: `number_manufactor` == FleetMgmt `ACCDEVICES.SerialNo`.
    `number` is the human Radix device id staff search by (e.g. "144052").
    `id` is the GUID handle used for all `/serialnumber/*` sub-calls.
    """

    id: str = Field(..., alias="id")
    number: str | None = None
    number_manufactor: str | None = Field(None, alias="numberManufactor")
    location: str | None = None
    customer_id: str | None = Field(None, alias="customerId")
    shipping_address_id: str | None = Field(None, alias="shippingAddressId")
    inactive: bool | None = None
    incoming_date: datetime | None = Field(None, alias="incomingDate")
    production_date: datetime | None = Field(None, alias="productionDate")
    warranty_supplier: str | None = Field(None, alias="warrantySupplier")
    article: RadixArticle | None = None


class RadixSerialDetail(_RadixModel):
    """An installed component / accessory on a device."""

    id: str | None = None
    article_id: str | None = Field(None, alias="articleId")
    article: str | None = None
    model: str | None = None
    serialnumber: str | None = None
    description: str | None = None
    quantity: int | None = None
    installation_date: datetime | None = Field(None, alias="installationDate")


class RadixContract(_RadixModel):
    """A contract bound to a device (the validity FleetMgmt lacks)."""

    id: str = Field(..., alias="id")
    code: str | None = None
    description: str | None = None
    valid_from: datetime | None = Field(None, alias="validFrom")
    valid_until: datetime | None = Field(None, alias="validUntil")
    is_done: bool | None = Field(None, alias="isDone")
    is_automatic_renewal: bool | None = Field(None, alias="isAutomaticRenewal")
    serialnumber_id: str | None = Field(None, alias="serialnumberId")
    customer_id: str | None = Field(None, alias="customerId")


class RadixCounter(_RadixModel):
    """A meter reading for a device (cross-check vs FleetMgmt counters)."""

    id: str | None = None
    serialnumber_id: str | None = Field(None, alias="serialnumberId")
    serialnumber: str | None = None
    serialnumber_number_manufactor: str | None = Field(None, alias="serialnumberNumberManufactor")
    serialnumber_location: str | None = Field(None, alias="serialnumberLocation")
    article_id: str | None = Field(None, alias="articleId")
    article_code: str | None = Field(None, alias="articleCode")
    article_searchtext: str | None = Field(None, alias="articleSearchtext")
    description: str | None = None
    counter_type: str | None = Field(None, alias="counterType")
    counter_kind_type: str | None = Field(None, alias="counterKindType")  # e.g. "TotalBlack"
    counter_type_id: str | None = Field(None, alias="counterTypeId")
    position: int | None = None
    monitoring: int | None = None
    contract: bool | None = None
    movement_reading_type: str | None = Field(None, alias="movementRadingType")
    movement_date: datetime | None = Field(None, alias="movementDate")
    movement_value: int | None = Field(None, alias="movementValue")
    acv: int | None = None


class RadixActivity(_RadixModel):
    """A service activity (ticket line).

    The activity header carries NO device serial — device linkage runs via
    `/serialnumber/tickets` -> `/ticket/activity` (or `/activity?TicketId=`).
    Contact persons and employee NAMES are omitted (PII); only pseudonymous
    employee ids are kept.
    """

    id: str = Field(..., alias="id")
    code: str | None = None
    ticket_id: str | None = Field(None, alias="ticketId")
    ticket_code: str | None = Field(None, alias="ticketCode")
    ticket_description: str | None = Field(None, alias="ticketDescription")
    technical_description: str | None = Field(None, alias="technicalDescription")
    date: datetime | None = None
    state: str | None = None
    state_code: str | None = Field(None, alias="stateCode")
    state_description: str | None = Field(None, alias="stateDescription")
    state_id: str | None = Field(None, alias="stateId")
    activity_type: str | None = Field(None, alias="activityType")
    activity_type_type: str | None = Field(None, alias="activityTypeType")
    activity_type_id: str | None = Field(None, alias="activityTypeId")
    invoice_type: str | None = Field(None, alias="invoiceType")
    invoice_type_id: str | None = Field(None, alias="invoiceTypeId")
    maintenance_type: str | None = Field(None, alias="maintenanceType")
    customer: str | None = None
    customer_id: str | None = Field(None, alias="customerId")
    customer_location: str | None = Field(None, alias="customerLocation")
    customer_town: str | None = Field(None, alias="customerTown")
    location: str | None = None
    town: str | None = None
    employee_id: str | None = Field(None, alias="employeeId")  # pseudonymous; no name
    employee_id_responsible: str | None = Field(None, alias="employeeIdResponsible")
    team_id: str | None = Field(None, alias="teamId")
    # Omitted PII: employee, employeeResponsible, contact, contactEmail,
    # contactFirstname, contactSurname, contactId, contactEmail.


class RadixWorkTime(_RadixModel):
    """A logged labour entry. Employee NAME omitted; only `employee_id` kept.

    `from`/`until` are seconds-of-day; `duration_minutes` derives the span.
    `to_billed` distinguishes billable from warranty/goodwill labour.
    """

    id: str = Field(..., alias="id")
    ticket_id: str | None = Field(None, alias="ticketId")
    activity_id: str | None = Field(None, alias="activityId")
    activity: str | None = None
    date: datetime | None = None
    period: float | None = None
    employee_id: str | None = Field(None, alias="employeeId")
    invoicing_type: str | None = Field(None, alias="invoicingType")
    invoicing_type_id: str | None = Field(None, alias="invoicingTypeId")
    open_time: bool | None = Field(None, alias="openTime")
    from_seconds: int | None = Field(None, alias="from")
    until_seconds: int | None = Field(None, alias="until")
    to_billed: bool | None = Field(None, alias="toBilled")

    @property
    def duration_minutes(self) -> float | None:
        """Labour span in minutes from the seconds-of-day window, if both set."""
        if self.from_seconds is None or self.until_seconds is None:
            return None
        return (self.until_seconds - self.from_seconds) / 60.0


class RadixSparePart(BaseModel):
    """A spare part used in an activity (material).

    Live payload not yet observed populated, so this is permissive
    (`extra="allow"`). Spare parts carry no personal data.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str | None = None
    activity_id: str | None = Field(None, alias="activityId")
    article_id: str | None = Field(None, alias="articleId")
    description: str | None = None
    quantity: float | None = None


class RadixSparePartPrice(BaseModel):
    """Material price (€) for a part/article. Permissive; confirm in Phase 3."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    article_id: str | None = Field(None, alias="articleId")
    serialnumber_id: str | None = Field(None, alias="serialnumberId")


class RadixCodeName(_RadixModel):
    """Generic lookup row (activity/ticket states, types, priorities)."""

    id: str | None = None
    code: str | None = None
    description: str | None = None
    state: str | None = None
    name: str | None = None
    type: str | None = None

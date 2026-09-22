import enum

import sqlalchemy as sa


class Skill(enum.StrEnum):
    """Требуемый навык заявки / навык инженера (см. TECHNICAL_CONSTRAINTS.md, §2)."""

    LOCAL_WORKS = "local_works"
    CONNECTION_AND_ORDERS = "connection_and_orders"
    EMERGENCY_WORKS = "emergency_works"


class VehicleType(enum.StrEnum):
    """Тип транспортного средства инженера (см. TECHNICAL_CONSTRAINTS.md, §2)."""

    CAR = "car"
    PEDESTRIAN = "pedestrian"
    BICYCLE = "bicycle"
    PUBLIC_TRANSPORT = "public_transport"


class RequestPriority(enum.IntEnum):
    """Приоритет заявки (`Request.priority`) — см. TECHNICAL_CONSTRAINTS.md, §2.

    Меньше число — важнее заявка. Единственная и основная шкала приоритета
    (не отдельная от "обычная/срочная" — та вычисляется из этого ранга, см.
    TECHNICAL_CONSTRAINTS.md). `Request.priority` в БД остаётся `int`
    (`ck_request_priority` уже проверяет диапазон 1-3) — этот enum не тип
    колонки, а именованная ссылка на конкретные значения ранга везде, где
    код должен явно сравнить приоритет с "аварией"/"подключением" и т.п.,
    вместо голого литерала `1`/`2`/`3`.
    """

    EMERGENCY = 1
    CONNECTION = 2
    REPAIR = 3


class RequestTypeBk(enum.StrEnum):
    """Тип заявки в Beekeeper (`Тип заявки BK`) — закрытый список по всем регионам датасета."""

    GLOBAL_PROBLEM = "global_problem"
    ADDITIONAL_ORDER = "additional_order"
    LOCAL_REQUEST = "local_request"
    CONNECTION = "connection"


class RequestTypeHd(enum.StrEnum):
    """Тип заявки в HelpDesk (`Тип заявки HD`) — закрытый список по всем регионам датасета."""

    IP_ADDRESS_169 = "ip_address_169"
    TVE_ENT_OTHER_ERRORS = "tve_ent_other_errors"
    TVE_ENT_SET_TOP_BOX_REPLACEMENT = "tve_ent_set_top_box_replacement"
    EMERGENCY = "emergency"
    EQUIPMENT_ADDITIONAL_ORDER = "equipment_additional_order"
    CONNECTION_OR_EQUIPMENT_ORDER = "connection_or_equipment_order"
    CONNECTION_REQUEST = "connection_request"
    INFORMATION = "information"
    SUBSCRIBER_CONVERGENCE = "subscriber_convergence"
    MONITORING = "monitoring"
    NO_LINK = "no_link"
    LOW_SPEED = "low_speed"
    GIGABIT_SWITCH = "gigabit_switch"
    CABLE_WORK = "cable_work"
    DISCONNECTS = "disconnects"
    PORT_ERROR_GROWTH = "port_error_growth"
    ROUTER_REPLACEMENT_BY_TECHNICIAN = "router_replacement_by_technician"
    TV_SET_TOP_BOX_REPLACEMENT = "tv_set_top_box_replacement"


class ConnectionType(enum.StrEnum):
    """Технология подключения (`Подключение`) — встречается только в части регионов датасета."""

    FMC = "fmc"
    FTTB = "fttb"


class RequestStatus(enum.StrEnum):
    """Статус заявки (`Статус BK`) — закрытый список из "Контрольное распределение"."""

    NOT_SENT = "not_sent"
    SENT = "sent"
    ON_THE_WAY = "on_the_way"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


class PlanKind(enum.StrEnum):
    """Тип плана — что его породило (см. три кейса планирования в SUMMARY.md)."""

    INITIAL = "initial"
    MANUAL_REPLAN = "manual_replan"
    EVENT_REPLAN = "event_replan"


class ReplanningEventType(enum.StrEnum):
    """Тип внештатного события, требующего перепланирования.

    См. TECHNICAL_CONSTRAINTS.md, §2, §4.
    """

    URGENT_REQUEST = "urgent_request"
    REQUEST_CANCELLED = "request_cancelled"
    ENGINEER_UNAVAILABLE = "engineer_unavailable"


class UnassignedReason(enum.StrEnum):
    """Причина, по которой заявка не попала ни в один `PlanStop` плана.

    Закрытый список ровно по формулировкам TECHNICAL_CONSTRAINTS.md, §3.
    """

    NO_MATCHING_SKILL = "no_matching_skill"
    NO_MATCHING_VEHICLE = "no_matching_vehicle"
    NO_TIME_SLOT = "no_time_slot"
    NO_AVAILABLE_ENGINEER = "no_available_engineer"


class Region(enum.StrEnum):
    """Округ — независимый регион/пул исполнителей (см. TECHNICAL_CONSTRAINTS.md, §1).

    В исходном экселе явной колонки "Округ" нет — округ соответствует конкретному
    файлу выгрузки (Восток/Юго-восток/Югоцентр), а "Район" — более мелкое деление
    внутри округа. Инженер закреплён за одним округом и не переключается между ними,
    поэтому округ должен быть явным полем и у заявки, и у инженера.
    """

    VOSTOK = "vostok"
    YUGO_VOSTOK = "yugo_vostok"
    YUGOTSENTR = "yugotsentr"


# Общие postgres ENUM-типы: заводятся один раз здесь и переиспользуются в моделях,
# чтобы Alembic не пытался создать один и тот же тип дважды под разными объектами.
skill_enum = sa.Enum(Skill, name="skill")
vehicle_type_enum = sa.Enum(VehicleType, name="vehicle_type")
request_type_bk_enum = sa.Enum(RequestTypeBk, name="request_type_bk")
request_type_hd_enum = sa.Enum(RequestTypeHd, name="request_type_hd")
connection_type_enum = sa.Enum(ConnectionType, name="connection_type")
request_status_enum = sa.Enum(RequestStatus, name="request_status")
region_enum = sa.Enum(Region, name="region")
plan_kind_enum = sa.Enum(PlanKind, name="plan_kind")
replanning_event_type_enum = sa.Enum(ReplanningEventType, name="replanning_event_type")
unassigned_reason_enum = sa.Enum(UnassignedReason, name="unassigned_reason")

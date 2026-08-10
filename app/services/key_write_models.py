from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class KeyWriteAction(StrEnum):
    REASSIGN = "reassign"
    ADD_PANELS = "add_panels"
    NO_ACTION = "no_action"
    INVALID = "invalid"


class KeyWriteUiStatus(StrEnum):
    READY = "ready"
    OCCUPIED = "occupied"
    ACTION_REQUIRED = "action_required"
    ALREADY_ALL = "already_all"
    PARTIAL = "partial"
    SUCCESS = "success"
    FAILED = "failed"


class WriteErrorCode(StrEnum):
    TIMEOUT = "timeout"
    AUTH = "auth"
    NETWORK = "network"
    REJECTED = "rejected"
    INVALID_RESPONSE = "invalid_response"
    ALREADY_EXISTS = "already_exists"
    UNKNOWN = "unknown"


class _ReadOnlyMapping(Mapping[str, Any]):
    def as_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())


def _ints(values) -> frozenset[int]:
    return frozenset(int(value) for value in (values or ()) if int(value) > 0)


@dataclass(frozen=True)
class KeyWriteContext(_ReadOnlyMapping):
    key_id: int
    key_type: str = ""
    key_number: str = ""
    hex_value: str = ""
    is_used: bool = False
    assignment: Mapping[str, Any] = field(default_factory=dict)
    assignments: tuple[Mapping[str, Any], ...] = ()
    panels: tuple[Mapping[str, Any], ...] = ()
    known_panel_ids: frozenset[int] = frozenset()
    selected_panel_ids: frozenset[int] = frozenset()
    already_present_panel_ids: frozenset[int] = frozenset()
    missing_panel_ids: frozenset[int] = frozenset()
    write_state: str = "free"
    description: str = ""
    operator_decision_required: bool = False
    allowed_actions: tuple[KeyWriteAction, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def key_hex(self) -> str:
        return self.hex_value

    @property
    def is_free(self) -> bool:
        return not self.is_used

    @property
    def is_occupied(self) -> bool:
        return self.is_used

    @property
    def current_assignment(self) -> Mapping[str, Any]:
        return self.assignment

    @property
    def assignment_history_summary(self) -> tuple[Mapping[str, Any], ...]:
        return self.assignments

    @property
    def requires_operator_decision(self) -> bool:
        return self.operator_decision_required

    @property
    def ui_status(self) -> KeyWriteUiStatus:
        if self.write_state == "all_selected":
            return KeyWriteUiStatus.ALREADY_ALL
        if self.write_state in {"partial_selected"}:
            return KeyWriteUiStatus.PARTIAL
        if self.write_state in {"conflict", "missing"}:
            return KeyWriteUiStatus.FAILED
        if self.operator_decision_required:
            return KeyWriteUiStatus.ACTION_REQUIRED
        return KeyWriteUiStatus.READY

    @classmethod
    def from_legacy(
        cls,
        value: Mapping[str, Any] | None,
        *,
        selected_panel_ids=(),
        write_state: str | None = None,
        description: str = "",
    ) -> "KeyWriteContext":
        source = dict(value or {})
        known = _ints(source.get("panel_ids"))
        selected = _ints(selected_panel_ids)
        already = known & selected
        missing = selected - known
        is_used = bool(source.get("is_used"))
        assignment = {
            "id": source.get("assignment_id"),
            "type": source.get("assignment_type") or "",
            "type_name": source.get("assignment_type_name") or "",
            "address": source.get("assignment_address") or "",
            "apartment": source.get("assignment_apartment") or "",
            "owner_name": source.get("owner_name") or "",
            "assigned_at": source.get("assigned_at"),
        }
        resolved_state = write_state or source.get("write_state") or (
            "used" if is_used else "free"
        )
        return cls(
            key_id=int(source.get("key_id") or source.get("id") or 0),
            key_type=source.get("key_type_name") or source.get("type_name") or "",
            key_number=str(source.get("key_number") or source.get("number") or ""),
            hex_value=str(source.get("hex_value") or ""),
            is_used=is_used,
            assignment=MappingProxyType(assignment),
            assignments=tuple(MappingProxyType(dict(item)) for item in source.get("assignments", ())),
            panels=tuple(MappingProxyType(dict(item)) for item in source.get("panels", ())),
            known_panel_ids=known,
            selected_panel_ids=selected,
            already_present_panel_ids=already,
            missing_panel_ids=missing,
            write_state=resolved_state,
            description=description or source.get("description") or "",
            operator_decision_required=is_used,
            allowed_actions=(KeyWriteAction.REASSIGN, KeyWriteAction.ADD_PANELS) if is_used else (KeyWriteAction.NO_ACTION,),
            raw=MappingProxyType(source),
        )

    def as_dict(self) -> dict[str, Any]:
        result = dict(self.raw)
        result.update(
            {
                "key_id": self.key_id,
                "key_type_name": self.key_type,
                "key_number": self.key_number,
                "hex_value": self.hex_value,
                "key_hex": self.key_hex,
                "is_used": self.is_used,
                "is_free": self.is_free,
                "is_occupied": self.is_occupied,
                "current_assignment": dict(self.current_assignment),
                "assignment_history_summary": [
                    dict(item) for item in self.assignment_history_summary
                ],
                "assignments": [dict(item) for item in self.assignments],
                "panels": [dict(item) for item in self.panels],
                "panel_ids": sorted(self.known_panel_ids),
                "selected_panel_ids": sorted(self.selected_panel_ids),
                "already_present_panel_ids": sorted(self.already_present_panel_ids),
                "missing_panel_ids": sorted(self.missing_panel_ids),
                "write_state": self.write_state,
                "ui_status": self.ui_status.value,
                "description": self.description,
                "operator_decision_required": self.operator_decision_required,
                "requires_operator_decision": self.requires_operator_decision,
                "allowed_actions": [action.value for action in self.allowed_actions],
                "known_panel_ids_csv": ",".join(str(value) for value in sorted(self.known_panel_ids)),
            }
        )
        return result


@dataclass(frozen=True)
class KeyWriteDecision(_ReadOnlyMapping):
    action: KeyWriteAction
    action_required: bool
    assignment_policy: str
    write_option: str
    known_panel_ids: frozenset[int]
    previous_assignment: str
    allowed_actions: tuple[KeyWriteAction, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "action_required": self.action_required,
            "assignment_policy": self.assignment_policy,
            "write_option": self.write_option,
            "known_panel_ids": set(self.known_panel_ids),
            "previous_assignment": self.previous_assignment,
            "allowed_actions": [action.value for action in self.allowed_actions],
        }


def classify_error(status: str, message: str = "") -> WriteErrorCode | None:
    token = f"{status} {message}".upper()
    if status in {"ALREADY_EXISTS", "ALREADY_ON_PANEL"}:
        return WriteErrorCode.ALREADY_EXISTS
    if "TIMEOUT" in token or "ВРЕМЯ ОЖИДАНИЯ" in token:
        return WriteErrorCode.TIMEOUT
    if "AUTH" in token or "АВТОРИЗ" in token:
        return WriteErrorCode.AUTH
    if "NETWORK" in token or "СЕТ" in token or "НЕДОСТУП" in token:
        return WriteErrorCode.NETWORK
    if "INVALID" in token or "НЕПОЛН" in token or "ФОРМАТ" in token:
        return WriteErrorCode.INVALID_RESPONSE
    if "REJECT" in token or "ОТКЛОН" in token:
        return WriteErrorCode.REJECTED
    return WriteErrorCode.UNKNOWN if status not in {"SUCCESS", "TRAINING_MODE", "DRY_RUN"} else None


@dataclass(frozen=True)
class PanelWriteResult:
    panel_id: int | None
    panel_name: str
    address: str
    status: str
    success: bool
    skipped: bool
    already_present: bool
    written: bool
    error_code: WriteErrorCode | None
    message: str
    technical_details: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_legacy(cls, value: Mapping[str, Any]) -> "PanelWriteResult":
        source = dict(value)
        panel = dict(source.get("panel") or {})
        status = str(source.get("status") or "UNKNOWN")
        already = status in {"ALREADY_EXISTS", "ALREADY_ON_PANEL"}
        skipped = already or status in {"TRAINING_MODE", "DRY_RUN", "SKIPPED"}
        message = str(source.get("message") or source.get("response") or "")
        return cls(
            panel_id=int(panel["id"]) if panel.get("id") else None,
            panel_name=str(panel.get("name") or panel.get("entrance") or ""),
            address=str(panel.get("address") or ""),
            status=status,
            success=bool(source.get("ok")) or already,
            skipped=skipped,
            already_present=already,
            written=bool(source.get("written")),
            error_code=classify_error(status, message),
            message=message,
            technical_details=MappingProxyType(source),
        )

    def to_legacy(self) -> dict[str, Any]:
        return dict(self.technical_details)


@dataclass(frozen=True)
class KeyWriteResult:
    overall_status: KeyWriteUiStatus
    key_id: int | None
    requested_panel_ids: tuple[int, ...]
    succeeded_panel_ids: tuple[int, ...]
    failed_panel_ids: tuple[int, ...]
    skipped_panel_ids: tuple[int, ...]
    already_present_panel_ids: tuple[int, ...]
    partial_success: bool
    error_code: WriteErrorCode | None
    user_message: str
    panel_results: tuple[PanelWriteResult, ...]
    technical_details: Mapping[str, Any] = field(default_factory=dict, repr=False)
    crm_summary: Mapping[str, Any] = field(default_factory=dict)

    @property
    def requested_panels(self) -> tuple[int, ...]:
        return self.requested_panel_ids

    @property
    def succeeded_panels(self) -> tuple[int, ...]:
        return self.succeeded_panel_ids

    @property
    def failed_panels(self) -> tuple[int, ...]:
        return self.failed_panel_ids

    @property
    def skipped_panels(self) -> tuple[int, ...]:
        return self.skipped_panel_ids

    @property
    def already_present_panels(self) -> tuple[int, ...]:
        return self.already_present_panel_ids

    @classmethod
    def from_writer(cls, key_id: int | None, values: list[Mapping[str, Any]]) -> "KeyWriteResult":
        panels = tuple(PanelWriteResult.from_legacy(value) for value in values)
        requested = tuple(item.panel_id for item in panels if item.panel_id is not None)
        succeeded = tuple(item.panel_id for item in panels if item.panel_id is not None and item.success and not item.already_present)
        failed = tuple(item.panel_id for item in panels if item.panel_id is not None and not item.success)
        skipped = tuple(item.panel_id for item in panels if item.panel_id is not None and item.skipped)
        already = tuple(item.panel_id for item in panels if item.panel_id is not None and item.already_present)
        if not panels:
            overall = KeyWriteUiStatus.FAILED
        elif len(already) == len(panels):
            overall = KeyWriteUiStatus.ALREADY_ALL
        elif failed and (succeeded or already):
            overall = KeyWriteUiStatus.PARTIAL
        elif failed and not succeeded and not already:
            overall = KeyWriteUiStatus.FAILED
        else:
            overall = KeyWriteUiStatus.SUCCESS
        first_error = next((item.error_code for item in panels if item.error_code and not item.already_present), None)
        message = "Операция выполнена частично" if overall == KeyWriteUiStatus.PARTIAL else "Запись завершена" if overall != KeyWriteUiStatus.FAILED else "Не удалось записать ключ"
        return cls(overall, key_id, requested, succeeded, failed, skipped, already, overall == KeyWriteUiStatus.PARTIAL, first_error, message, panels)

    @classmethod
    def from_uk(cls, key_id: int | None, value: Mapping[str, Any]) -> "KeyWriteResult":
        source = dict(value)
        panel_values = []
        for item in source.get("results", ()): 
            panel_values.append({
                **dict(item),
                "panel": {
                    "id": item.get("panel_id") or item.get("panel_link_id"),
                    "name": item.get("panel_name", ""),
                    "address": item.get("address", ""),
                },
                "written": bool(item.get("ok")),
            })
        result = cls.from_writer(key_id, panel_values)
        return cls(
            overall_status=result.overall_status,
            key_id=key_id,
            requested_panel_ids=result.requested_panel_ids,
            succeeded_panel_ids=result.succeeded_panel_ids,
            failed_panel_ids=result.failed_panel_ids,
            skipped_panel_ids=result.skipped_panel_ids,
            already_present_panel_ids=result.already_present_panel_ids,
            partial_success=result.partial_success,
            error_code=result.error_code,
            user_message=result.user_message,
            panel_results=result.panel_results,
            technical_details=MappingProxyType(source),
            crm_summary=MappingProxyType({
                "issue_id": source.get("issue_id"),
                "programming_id": source.get("programming_id"),
                "success_count": source.get("success_count", 0),
                "error_count": source.get("error_count", 0),
            }),
        )

    def to_legacy_results(self) -> list[dict[str, Any]]:
        return [item.to_legacy() for item in self.panel_results]

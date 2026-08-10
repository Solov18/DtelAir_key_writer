from app.repositories.key_repository import get_key_write_contexts
from app.services.key_write_models import KeyWriteAction, KeyWriteContext, KeyWriteDecision


OCCUPIED_ACTIONS = {"reassign", "add_panels"}


def describe_key_write_context(context) -> str:
    parts = [context.get("assignment_type_name") or "Назначение"]
    if context.get("assignment_address"):
        parts.append(context["assignment_address"])
    apartment = (context.get("assignment_apartment") or "").strip()
    if apartment:
        parts.append(f"кв. {apartment}")
    if context.get("owner_name"):
        parts.append(context["owner_name"])
    return ", ".join(parts)


def enrich_key_write_rows(rows: list[dict], panels: list[dict]) -> bool:
    key_ids = [row["item"]["id"] for row in rows if row.get("item")]
    contexts = get_key_write_contexts(key_ids)
    selected_panel_ids = {int(panel["id"]) for panel in panels}
    has_used_keys = False

    for row in rows:
        item = row.get("item") or {}
        context = {
            **item,
            **contexts.get(int(item.get("id") or 0), {}),
        }
        known_panel_ids = {int(value) for value in context.get("panel_ids", [])}
        selected_known_ids = known_panel_ids & selected_panel_ids
        is_used = bool(context.get("is_used"))
        has_used_keys = has_used_keys or is_used

        if row.get("ambiguous"):
            write_state = "conflict"
        elif not item:
            write_state = "missing"
        elif selected_panel_ids and selected_known_ids == selected_panel_ids:
            write_state = "all_selected"
        elif selected_known_ids:
            write_state = "partial_selected"
        elif is_used:
            write_state = "used"
        else:
            write_state = "free"

        row["write_context"] = KeyWriteContext.from_legacy(
            context,
            selected_panel_ids=selected_panel_ids,
            write_state=write_state,
            description=describe_key_write_context(context) if is_used else "",
        )
    return has_used_keys


def get_key_write_context(key_id: int, panels: list[dict] | None = None) -> KeyWriteContext:
    row = {"item": {"id": int(key_id)}}
    enrich_key_write_rows([row], panels or [])
    return row["write_context"]


def resolve_key_write_decision(context, occupied_action: str = "") -> KeyWriteDecision:
    is_used = bool(context.get("is_used"))
    action_required = is_used and occupied_action not in OCCUPIED_ACTIONS
    assignment_policy = (
        "preserve" if is_used and occupied_action == "add_panels" else "replace"
    )
    write_option = (
        "add_selected_panels"
        if assignment_policy == "preserve"
        else "reassign_to_new_address"
        if is_used
        else "write_free_key"
    )
    action = (
        KeyWriteAction(occupied_action)
        if occupied_action in OCCUPIED_ACTIONS
        else KeyWriteAction.INVALID if action_required
        else KeyWriteAction.NO_ACTION
    )
    allowed = (
        (KeyWriteAction.REASSIGN, KeyWriteAction.ADD_PANELS)
        if is_used else (KeyWriteAction.NO_ACTION,)
    )
    return KeyWriteDecision(
        action=action,
        action_required=action_required,
        assignment_policy=assignment_policy,
        write_option=write_option,
        known_panel_ids=frozenset(int(value) for value in context.get("panel_ids", [])),
        previous_assignment=describe_key_write_context(context),
        allowed_actions=allowed,
    )

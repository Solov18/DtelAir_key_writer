import unittest

from app.services.key_write_context import resolve_key_write_decision
from app.services.key_write_models import (
    KeyWriteAction,
    KeyWriteContext,
    KeyWriteResult,
    KeyWriteUiStatus,
    WriteErrorCode,
)
from app.services.uk_keys import adapt_issue_result


class KeyWriteModelCharacterizationTests(unittest.TestCase):
    def test_free_context_preserves_legacy_mapping_contract(self):
        context = KeyWriteContext.from_legacy(
            {
                "key_id": 7,
                "key_type_name": "Синий",
                "key_number": "0012",
                "hex_value": "A1B2C3D4",
                "is_used": False,
                "panel_ids": [],
            },
            selected_panel_ids=[10, 11],
        )

        self.assertEqual(context.key_id, 7)
        self.assertEqual(context.key_number, "0012")
        self.assertEqual(context.missing_panel_ids, frozenset({10, 11}))
        self.assertEqual(context.ui_status, KeyWriteUiStatus.READY)
        self.assertTrue(context.is_free)
        self.assertFalse(context.is_occupied)
        self.assertEqual(context.key_hex, "A1B2C3D4")
        self.assertFalse(context.requires_operator_decision)
        self.assertEqual(context["panel_ids"], [])
        self.assertFalse(context["is_used"])

    def test_occupied_context_characterizes_partial_and_all_selected(self):
        source = {
            "key_id": 8,
            "is_used": True,
            "panel_ids": [10, 12],
            "assignment_type": "resident",
            "assignment_type_name": "Жилец",
            "assignment_address": "ул. Тестовая 1",
            "assignment_apartment": "3",
        }
        partial = KeyWriteContext.from_legacy(source, selected_panel_ids=[10, 11], write_state="partial_selected")
        all_selected = KeyWriteContext.from_legacy(source, selected_panel_ids=[10, 12], write_state="all_selected")

        self.assertEqual(partial.already_present_panel_ids, frozenset({10}))
        self.assertEqual(partial.missing_panel_ids, frozenset({11}))
        self.assertEqual(partial.ui_status, KeyWriteUiStatus.PARTIAL)
        self.assertEqual(all_selected.ui_status, KeyWriteUiStatus.ALREADY_ALL)
        self.assertTrue(partial.operator_decision_required)
        self.assertTrue(partial.requires_operator_decision)

    def test_decision_is_single_source_for_reassign_add_and_missing_choice(self):
        context = KeyWriteContext.from_legacy({"key_id": 8, "is_used": True, "panel_ids": [10]})

        missing = resolve_key_write_decision(context, "")
        reassign = resolve_key_write_decision(context, "reassign")
        add = resolve_key_write_decision(context, "add_panels")

        self.assertEqual(missing.action, KeyWriteAction.INVALID)
        self.assertTrue(missing["action_required"])
        self.assertEqual(reassign.action, KeyWriteAction.REASSIGN)
        self.assertEqual(reassign["assignment_policy"], "replace")
        self.assertEqual(add.action, KeyWriteAction.ADD_PANELS)
        self.assertEqual(add["assignment_policy"], "preserve")

    def test_writer_adapter_characterizes_partial_timeout_auth_and_already(self):
        result = KeyWriteResult.from_writer(
            9,
            [
                {"panel": {"id": 1, "name": "A"}, "status": "SUCCESS", "ok": True, "written": True},
                {"panel": {"id": 2, "name": "B"}, "status": "TIMEOUT", "ok": False, "message": "timeout"},
                {"panel": {"id": 3, "name": "C"}, "status": "AUTH_ERROR", "ok": False, "message": "auth"},
                {"panel": {"id": 4, "name": "D"}, "status": "ALREADY_EXISTS", "ok": True},
            ],
        )

        self.assertEqual(result.overall_status, KeyWriteUiStatus.PARTIAL)
        self.assertEqual(result.succeeded_panel_ids, (1,))
        self.assertEqual(result.failed_panel_ids, (2, 3))
        self.assertEqual(result.already_present_panel_ids, (4,))
        self.assertEqual(result.panel_results[1].error_code, WriteErrorCode.TIMEOUT)
        self.assertEqual(result.panel_results[2].error_code, WriteErrorCode.AUTH)
        self.assertEqual(result.to_legacy_results()[0]["status"], "SUCCESS")

    def test_writer_adapter_characterizes_total_failure_all_already_and_dry_run(self):
        failed = KeyWriteResult.from_writer(1, [{"panel": {"id": 2}, "status": "ERROR", "ok": False}])
        already = KeyWriteResult.from_writer(1, [{"panel": {"id": 2}, "status": "ALREADY_EXISTS", "ok": True}])
        dry_run = KeyWriteResult.from_writer(1, [{"panel": {"id": 2}, "status": "DRY_RUN", "ok": True}])

        self.assertEqual(failed.overall_status, KeyWriteUiStatus.FAILED)
        self.assertEqual(already.overall_status, KeyWriteUiStatus.ALREADY_ALL)
        self.assertEqual(already.already_present_panel_ids, (2,))
        self.assertEqual(dry_run.overall_status, KeyWriteUiStatus.SUCCESS)
        self.assertEqual(dry_run.skipped_panel_ids, (2,))

    def test_empty_panel_result_is_explicit_and_has_canonical_aliases(self):
        result = KeyWriteResult.from_writer(1, [])

        self.assertEqual(result.overall_status, KeyWriteUiStatus.FAILED)
        self.assertEqual(result.requested_panels, ())
        self.assertEqual(result.succeeded_panels, ())
        self.assertEqual(result.failed_panels, ())
        self.assertFalse(result.partial_success)

    def test_uk_adapter_keeps_issue_metadata_without_merging_engines(self):
        result = adapt_issue_result(
            12,
            {
                "issue_id": 41,
                "programming_id": 51,
                "success_count": 1,
                "error_count": 0,
                "results": [{"panel_id": 6, "panel_name": "Вход", "status": "SUCCESS", "ok": True}],
            },
        )

        self.assertEqual(result.succeeded_panel_ids, (6,))
        self.assertEqual(result.crm_summary["issue_id"], 41)
        self.assertEqual(result.crm_summary["programming_id"], 51)


if __name__ == "__main__":
    unittest.main()

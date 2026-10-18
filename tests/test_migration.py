"""Validate preservation, evidence semantics, and recoverable v1 upgrades."""
import copy
from pathlib import Path
from unittest import mock

from support import DataTestCase, records, tree
import migrate


class MigrationTest(DataTestCase):
    def test_preview_is_read_only_and_apply_preserves_originals_and_backup(self):
        self.copy_fixture()
        before = tree(self.root)
        preview = migrate.migrate(self.root, dry_run=True, today="2026-10-19")
        self.assertTrue(preview["changes_pending"])
        self.assertEqual(tree(self.root), before)
        result = migrate.migrate(self.root, today="2026-10-19")
        backup = Path(result["legacy_dir"])
        for name, content in before.items():
            self.assertEqual((backup / name).read_bytes(), content)
            if name != "growth-log.md":
                self.assertEqual((self.root / name).read_bytes(), content)
        self.assertFalse(records.status(self.root, today="2026-10-19")["migration_needed"])
        self.assertTrue(result["records_created"] > 0)
        self.assertFalse(migrate.migrate(self.root, today="2026-10-19")["changed"])

    def test_unverified_third_party_withdrawn_and_demo_do_not_become_independent_evidence(self):
        self.copy_fixture()
        migrate.migrate(self.root, today="2026-10-19")
        view = self.view()
        for record in view.valid:
            origin = record.get("migrated_from", {})
            independent = any(w["kind"] == "independent" for w in record.get("user_work", []))
            if origin.get("owner") == "third_party" or origin.get("status") == "unverified":
                self.assertFalse(independent)
            if origin.get("kind") == "model_demo":
                self.assertFalse(independent)
        self.assertTrue(view.invalidated_by)
        self.assertEqual(view.applied, [])
        self.assertIn("custom.experiment-design", records.known_ability_ids(view.state))
        self.assertEqual(len(view.state["ability_history"]), 1)

    def test_conflicting_v2_record_stops_before_backup_or_state_update(self):
        self.copy_fixture()
        plan, actions = migrate.build_plan(self.root, today="2026-10-19")
        conflicting = copy.deepcopy(actions["create"][0])
        conflicting["summary"] = "已存在的另一条真实内容"
        conflicting["recorded_at"] = "2026-10-01T00:00:00.000000+00:00"
        records.atomic_write_json(self.root / "records" / f"{conflicting['record_id']}.json", conflicting)
        before = tree(self.root)
        with self.assertRaisesRegex(ValueError, "冲突|中止"):
            migrate.migrate(self.root, today="2026-10-19")
        after = tree(self.root)
        self.assertEqual({k: v for k, v in after.items() if k != ".pm-grow.lock"}, before)
        self.assertFalse((self.root / "legacy-v1").exists())

    def test_interrupted_record_writes_can_resume_without_duplication(self):
        self.copy_fixture()
        original = migrate.atomic_write_json
        count = 0

        def interrupted(path, value):
            nonlocal count
            if Path(path).parent.name == "records":
                count += 1
                if count == 2:
                    raise OSError("simulated interrupted migration")
            return original(path, value)

        with mock.patch.object(migrate, "atomic_write_json", interrupted):
            with self.assertRaises(OSError):
                migrate.migrate(self.root, today="2026-10-19")
        self.assertEqual(len(list((self.root / "records").glob("*.json"))), 1)
        resumed = migrate.migrate(self.root, today="2026-10-19")
        self.assertTrue(resumed["changed"])
        self.assertFalse(records.status(self.root, today="2026-10-19")["migration_needed"])
        self.assertFalse(migrate.migrate(self.root, today="2026-10-19")["changed"])

    def test_invalid_old_input_is_rejected_without_creating_v2_records(self):
        self.copy_fixture()
        path = self.root / "events/ev-early.json"
        path.write_text('{"event_id":"bad"}')
        with self.assertRaises(ValueError):
            migrate.migrate(self.root, today="2026-10-19")
        self.assertFalse((self.root / "records").exists())
        self.assertFalse((self.root / "state.json").exists())

    def test_absent_source_is_not_created_even_for_apply(self):
        self.assertFalse(migrate.migrate(self.root, dry_run=True)["needed"])
        self.assertFalse(migrate.migrate(self.root)["changed"])
        self.assertFalse(self.root.exists())

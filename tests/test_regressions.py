from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_sn_notion():
    """Load sn_notion without requiring the sibling crm-core checkout."""
    sys.modules.pop("sn_notion", None)
    sys.modules.pop("crmcore_notion_client", None)
    fake_client = types.ModuleType("crmcore_notion_client")
    fake_client.load_token = mock.Mock(return_value="token")
    fake_client.notion = mock.Mock()
    fake_loader = SimpleNamespace(exec_module=lambda module: None)
    fake_spec = SimpleNamespace(loader=fake_loader)
    with (
        mock.patch.object(importlib.util, "spec_from_file_location", return_value=fake_spec),
        mock.patch.object(importlib.util, "module_from_spec", return_value=fake_client),
    ):
        module = importlib.import_module("sn_notion")
    return module


def rich_block(block_id: str, kind: str, text: str) -> dict:
    return {
        "id": block_id,
        "type": kind,
        kind: {"rich_text": [{"plain_text": text}]},
    }


class ExtractorRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extract = importlib.import_module("sn_extract")

    def test_company_search_escapes_query_string_values(self):
        name = 'ACME "West" \\ Ops'
        with (
            mock.patch.object(self.extract.chrome, "open_url") as open_url,
            mock.patch.object(self.extract.chrome, "assert_logged_in"),
            mock.patch.object(self.extract.pace, "pause_navigation"),
            mock.patch.object(self.extract, "_js", return_value=[]),
        ):
            self.extract.search_company(name)

        query = parse_qs(urlparse(open_url.call_args.args[0]).query)["query"][0]
        self.assertEqual(
            query,
            f"(spellCorrectionEnabled:false,keywords:{json.dumps(name, ensure_ascii=False)})",
        )

    def test_empty_normalised_hit_never_prefix_matches(self):
        self.assertIsNone(
            self.extract.pick_match(
                "Beacon",
                [{"name": "AI", "id": "wrong", "blurb": "100 employees"}],
            )
        )

    def test_mutual_read_checks_auth_before_parsing_empty_page(self):
        with (
            mock.patch.object(self.extract.chrome, "open_url"),
            mock.patch.object(self.extract.pace, "pause_between_lead_pages"),
            mock.patch.object(
                self.extract.chrome,
                "assert_logged_in",
                side_effect=self.extract.chrome.DependencyError("auth wall"),
            ),
            mock.patch.object(self.extract, "_js") as parse,
        ):
            with self.assertRaises(self.extract.chrome.DependencyError):
                self.extract.mutual_names("lead-id")
        parse.assert_not_called()

    def test_thin_account_skips_discarded_tail_reads(self):
        with (
            mock.patch.object(
                self.extract,
                "read_account",
                return_value={"people": [], "thin": True},
            ),
            mock.patch.object(self.extract, "read_tail") as read_tail,
        ):
            result = self.extract.scan_company("Acme", company_id="123")

        self.assertTrue(result["thin"])
        self.assertEqual(result["company_id"], "123")
        read_tail.assert_not_called()


class NotionRegressionTests(unittest.TestCase):
    def setUp(self):
        self.notion = load_sn_notion()

    @staticmethod
    def person(**overrides):
        person = {
            "name": "Jane Doe",
            "title": "CEO",
            "degree": "1st",
            "lead_id": "lead-1",
        }
        person.update(overrides)
        return person

    def test_write_uses_current_date_instead_of_hard_coded_date(self):
        self.notion.nc.notion.side_effect = [
            {},  # page property PATCH
            {"results": [], "has_more": False},  # body children GET
            {},  # body children PATCH
        ]

        self.notion.write(
            "page-id",
            [self.person()],
            ["Angle"],
            token="token",
        )

        page_patch = self.notion.nc.notion.call_args_list[0]
        props = page_patch.args[2]["properties"]
        checked = props[self.notion.PROPS["warmPathCheckedAt"]]["date"]["start"]
        self.assertEqual(checked, date.today().isoformat())

    def test_thin_scan_never_writes_or_marks_checked(self):
        result = self.notion.write(
            "page-id",
            [self.person()],
            ["Angle"],
            token="token",
            thin=True,
        )

        self.assertEqual(result, "degraded")
        self.notion.nc.notion.assert_not_called()

    def test_write_allowlist_is_warm_path_fields_only(self):
        self.notion.nc.notion.side_effect = [
            {},
            {"results": [], "has_more": False},
            {},
        ]
        self.notion.write(
            "page-id",
            [self.person()],
            ["Angle"],
            moves=["HIRE · Someone"],
            token="token",
        )
        props = self.notion.nc.notion.call_args_list[0].args[2]["properties"]
        allowed = self.notion.warm_path_allowed_properties()
        self.assertEqual(set(props), allowed)
        for forbidden in (
            "Status",
            "Fit Score",
            "Fit Raw",
            "Relationship Notes",
            "Current Angle",
            "Last Touched",
            "Re-check",
        ):
            self.assertNotIn(forbidden, props)

    def test_assert_warm_path_write_refuses_status_and_fit(self):
        with self.assertRaisesRegex(ValueError, "Status"):
            self.notion.assert_warm_path_write({"Status": {"select": {"name": "Prospect"}}})
        with self.assertRaisesRegex(ValueError, "Fit Score"):
            self.notion.assert_warm_path_write({"Fit Score": {"number": 90}})
        with self.assertRaisesRegex(ValueError, "Fit: Growth"):
            self.notion.assert_warm_path_write({"Fit: Growth": {"number": 1}})
        with self.assertRaisesRegex(ValueError, "Relationship Notes"):
            self.notion.assert_warm_path_write(
                {"Relationship Notes": {"rich_text": []}})
        with self.assertRaisesRegex(ValueError, "Current Angle"):
            self.notion.assert_warm_path_write({"Current Angle": {"rich_text": []}})
        with self.assertRaisesRegex(ValueError, "Last Touched"):
            self.notion.assert_warm_path_write(
                {"Last Touched": {"date": {"start": "2026-08-12"}}})
        with self.assertRaisesRegex(ValueError, "Re-check"):
            self.notion.assert_warm_path_write({"Re-check": {"checkbox": True}})

    def test_resolve_database_id_defaults_to_crmx_and_refuses_legacy(self):
        self.assertEqual(
            self.notion.resolve_database_id({"notionDatabaseId": self.notion.CRMX_DEFAULT_DB}),
            self.notion.CRMX_DEFAULT_DB,
        )
        with self.assertRaisesRegex(RuntimeError, "legacy crm-core"):
            self.notion.resolve_database_id({
                "notionDatabaseId": self.notion.LEGACY_CRM_CORE_DB,
                "legacyCrmCoreDatabaseId": self.notion.LEGACY_CRM_CORE_DB,
            })
        with mock.patch.dict(
            "os.environ",
            {"SALESNAV_NOTION_DATABASE_ID": self.notion.LEGACY_CRM_CORE_DB},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "legacy crm-core"):
                self.notion.resolve_database_id({
                    "notionDatabaseId": self.notion.CRMX_DEFAULT_DB,
                    "legacyCrmCoreDatabaseId": self.notion.LEGACY_CRM_CORE_DB,
                })

    def test_config_targets_crmx_board_not_legacy_crm_core(self):
        config = json.loads((ROOT / "config" / "salesnav.json").read_text())
        self.assertEqual(
            config["notionDatabaseId"],
            "3b43930e-64f4-8136-a6ef-c8dfb4ac09a5",
        )
        self.assertNotEqual(
            config["notionDatabaseId"],
            config["legacyCrmCoreDatabaseId"],
        )
        self.assertEqual(config["propertyMap"]["linkedinUrl"], "LinkedIn")
        self.assertFalse(config["schemaReady"])

    def test_body_refresh_paginates_and_preserves_following_user_notes(self):
        first_page = [rich_block("intro", "paragraph", "Intro")] * 100
        legacy = [
            {"id": "divider", "type": "divider", "divider": {}},
            rich_block("heading", "heading_2", "Warm Paths"),
            rich_block("managed", "paragraph", "managed by sales-nav · last scan 2026-07-23"),
            rich_block(
                "path",
                "bulleted_list_item",
                "Jane Doe — CEO (1st) — you're connected; go direct.",
            ),
            rich_block("notes", "paragraph", "Customer notes — never delete this"),
        ]
        get_responses = iter(
            [
                {"results": first_page, "has_more": True, "next_cursor": "cursor / 2"},
                {"results": legacy, "has_more": False},
            ]
        )

        def notion(method, url, body=None, token=None):
            if method == "GET":
                return next(get_responses)
            return {}

        self.notion.nc.notion.side_effect = notion
        self.notion.write_body("page-id", [self.person()], "2026-07-27", "token")

        calls = self.notion.nc.notion.call_args_list
        self.assertIn("start_cursor=cursor%20%2F%202", calls[1].args[1])
        deleted = {
            call.args[1].rsplit("/", 1)[-1]
            for call in calls
            if call.args[0] == "DELETE"
        }
        self.assertEqual(deleted, {"divider", "heading", "managed", "path"})
        self.assertNotIn("notes", deleted)

        append = next(call for call in calls
                      if call.args[0] == "PATCH" and call.args[1].endswith("/children"))
        final_block = append.args[2]["children"][-1]
        self.assertEqual(self.notion._block_text(final_block), self.notion.BODY_END)


class RunnerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.notion = load_sn_notion()
        sys.modules.pop("sn_run", None)
        self.runner = importlib.import_module("sn_run")

    def test_parked_company_still_gets_between_company_pause(self):
        row = {
            "page_id": "page-id",
            "name": "Ambiguous Co",
            "fit": 90,
            "needs_sync": False,
        }
        args = SimpleNamespace(
            unmapped=False,
            refresh=False,
            backfill=False,
            shelf="Prospect",
            min_fit=None,
            dry_run=False,
        )
        with (
            mock.patch.object(self.runner.sn_notion, "select", return_value=[row]),
            mock.patch.object(
                self.runner.sn_extract,
                "scan_company",
                return_value={"error": "ambiguous_identity", "candidates": []},
            ),
            mock.patch.object(self.runner.pace, "claim_scan"),
            mock.patch.object(self.runner.pace, "remaining_today", return_value=10),
            mock.patch.object(self.runner.pace, "pause_between_companies") as pause,
        ):
            result = self.runner.run_batch(args, "token", cap=1)

        self.assertEqual(result["parked"], 1)
        pause.assert_called_once_with()

    def test_min_fit_does_not_treat_unknown_fit_as_zero(self):
        rows = [
            {"page_id": "known", "name": "Known", "fit": 90, "needs_sync": False},
            {"page_id": "unknown", "name": "Unknown", "fit": None, "needs_sync": False},
            {"page_id": "low", "name": "Low", "fit": 10, "needs_sync": False},
        ]
        args = SimpleNamespace(
            unmapped=False,
            refresh=False,
            backfill=False,
            shelf="Prospect",
            min_fit=50,
            dry_run=True,
        )
        with (
            mock.patch.object(self.runner.sn_notion, "select", return_value=rows),
            mock.patch.object(
                self.runner.sn_extract,
                "scan_company",
                return_value={
                    "company_id": "1",
                    "people": [{
                        "name": "A", "title": "CEO", "degree": "1st", "lead_id": "l",
                    }],
                },
            ),
            mock.patch.object(self.runner.pace, "claim_scan"),
            mock.patch.object(self.runner.pace, "remaining_today", return_value=10),
            mock.patch.object(self.runner.pace, "pause_between_companies"),
            mock.patch.object(self.runner, "load_ids", return_value={}),
            mock.patch.object(self.runner, "save_ids"),
        ):
            result = self.runner.run_batch(args, "token", cap=10)

        self.assertEqual(result["ok"], 1)
        self.assertEqual(result["queued"], 1)

    def test_cli_count_types_reject_negative_and_zero_bypasses(self):
        self.assertEqual(self.runner.nonnegative_int("0"), 0)
        self.assertEqual(self.runner.positive_int("1"), 1)
        with self.assertRaises(self.runner.argparse.ArgumentTypeError):
            self.runner.nonnegative_int("-1")
        with self.assertRaises(self.runner.argparse.ArgumentTypeError):
            self.runner.positive_int("0")

    def test_growth_net_adds_use_prior_headcount_as_percentage_base(self):
        # 500 is the current total. At +8%, the prior total was ~463, so the
        # company added ~37 people and should not cross the 40-add threshold.
        self.assertIsNone(self.runner.growth_angle({"total": "500", "g6": "8"}))
        angle = self.runner.growth_angle({"total": "540", "g6": "8"})
        self.assertIn("~40 net adds", angle)


class PacingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pace = importlib.import_module("lib.pace")

    def test_scan_claim_is_atomic_and_stops_at_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with (
                mock.patch.object(self.pace, "_LEDGER", directory / "daily.json"),
                mock.patch.object(self.pace, "_LEDGER_LOCK", directory / "daily.lock"),
                mock.patch.object(self.pace, "_CACHE", {"dailyCompanyCap": 1}),
            ):
                self.assertEqual(self.pace.claim_scan(), 1)
                with self.assertRaises(self.pace.DailyCapReached):
                    self.pace.claim_scan()
                self.assertEqual(self.pace.scans_today(), 1)

    def test_corrupt_ledger_fails_closed_instead_of_resetting_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            ledger = directory / "daily.json"
            ledger.write_text("{not valid json")
            with (
                mock.patch.object(self.pace, "_LEDGER", ledger),
                mock.patch.object(self.pace, "_LEDGER_LOCK", directory / "daily.lock"),
                mock.patch.object(self.pace, "_CACHE", {"dailyCompanyCap": 25}),
            ):
                with self.assertRaises(self.pace.DailyLedgerError):
                    self.pace.remaining_today()


if __name__ == "__main__":
    unittest.main()

"""The fault plan raises a job, holds the asset and names who to tell."""

import unittest

from plan_steps import args_for, ensure_issue_steps, fault_steps, finding_text

WHEEL = {"id": "C-4401", "name": "Coach 4401", "type": "coach wheelset", "line": "Pit line 2"}
CASTING = {"id": "CB-2231", "name": "Casting batch 2231", "type": "casting", "line": "Line 3"}
RAIL = {"out_of_service": "mark the coach sick", "work_order": "repair memo", "quarantine": "withdraw the wheel set"}
FACTORY = {"out_of_service": "take it out of service", "work_order": "repair job", "quarantine": "hold the batch"}
PEOPLE = ["Control room", "Lakshmi"]


class PlanStepsTest(unittest.TestCase):
    def test_dull_wheels_become_a_repair_memo(self) -> None:
        batch = {"parts": [{"n": 2, "result": "good"}, {"n": 4, "result": "dull"}]}
        finding = finding_text(WHEEL, None, batch)
        self.assertEqual(finding, "wheel 4 sounds dull")
        question, steps = fault_steps(WHEEL, RAIL, PEOPLE, finding, is_tap=True)
        tools = [s["tool"] for s in steps]
        self.assertIn("create_work_order", tools)
        self.assertIn("update_asset_status", tools)
        self.assertIn("notify_people", tools)
        self.assertIn("repair memo", question)
        self.assertEqual(args_for(WHEEL, None, batch, RAIL, PEOPLE, {}, "update_asset_status", finding)["status"], "sick")
        job = args_for(WHEEL, None, batch, RAIL, PEOPLE, {}, "create_work_order", finding)
        assert job is not None
        self.assertEqual(job["asset_id"], "C-4401")
        self.assertIn("wheel 4", job["title"])
        told = args_for(WHEEL, None, batch, RAIL, PEOPLE, {}, "notify_people", finding)
        assert told is not None
        self.assertEqual(told["people"], PEOPLE)

    def test_dull_casting_is_held_and_logged_as_a_job(self) -> None:
        batch = {"parts": [{"n": 3, "result": "dull"}]}
        finding = finding_text(CASTING, None, batch)
        _question, steps = fault_steps(CASTING, FACTORY, ["Suresh"], finding, is_tap=True)
        self.assertEqual([s["tool"] for s in steps], ["create_work_order", "quarantine_batch", "notify_people"])
        held = args_for(CASTING, None, batch, FACTORY, ["Suresh"], {}, "quarantine_batch", finding)
        assert held is not None
        self.assertEqual(held["parts"], [3])
        log = args_for(CASTING, None, batch, FACTORY, ["Suresh"], {}, "log_inspection", finding)
        assert log is not None
        self.assertEqual(log["result"], "fail")

    def test_a_model_plan_that_forgets_the_job_gets_it_added(self) -> None:
        steps, tools = ensure_issue_steps(
            [{"text": "Tell Suresh", "tool": "notify_people"}],
            ["notify_people"],
            CASTING, FACTORY, ["Suresh"], "part 3 sounds dull", is_tap=True,
        )
        names = {s["tool"] for s in steps} | set(tools)
        self.assertIn("create_work_order", names)
        self.assertIn("quarantine_batch", names)

    def test_unusual_sound_uses_the_cause(self) -> None:
        finding = finding_text({"type": "pump", "name": "Pump P-14", "id": "P-14"},
                               {"band": "very unusual", "label": "a worn bearing"}, None)
        self.assertIn("worn bearing", finding)
        job = args_for({"id": "P-14", "name": "Pump P-14", "type": "pump"},
                       {"label": "a worn bearing"}, None, FACTORY, ["Suresh"],
                       {"a worn bearing": "bearing"}, "reserve_part", finding)
        assert job is not None
        self.assertEqual(job["part"], "bearing")


if __name__ == "__main__":
    unittest.main()

"""Past issues stay attached to the machine and the numbered part."""

import unittest

from histories import build_histories, part_number


class HistoriesTest(unittest.TestCase):
    def test_a_wheel_number_is_read_from_the_title(self) -> None:
        self.assertEqual(part_number("Wheel 3 dull note"), 3)
        self.assertEqual(part_number("part 4 sounds dull"), 4)
        self.assertIsNone(part_number("Bearing change"))

    def test_issues_are_grouped_by_machine_and_part(self) -> None:
        assets = {"C-4401": {"last_serviced": "12 days ago", "notes": "", "status": "fit"}}
        orders = [
            {"id": "RM-1", "asset_id": "C-4401", "part": 3, "title": "Wheel 3 dull note"},
            {"id": "RM-2", "asset_id": "C-4402", "title": "Wheel 2 shelling"},
            {"id": "WO-1", "asset_id": "C-4401", "title": "Position 5 flat spot"},
        ]
        checks = [{"id": "IN-1", "asset_id": "C-4401", "notes": "wheel 3 sounds dull", "result": "fail"}]
        record = build_histories(assets, orders, checks)["C-4401"]
        self.assertEqual(record["last_serviced"], "12 days ago")
        self.assertEqual([i["id"] for i in record["issues"]], ["RM-1", "WO-1"])
        self.assertEqual(record["issues"][1]["part"], 5)
        self.assertEqual(record["inspections"][0]["part"], 3)


if __name__ == "__main__":
    unittest.main()

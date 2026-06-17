import unittest

from ngen_cal_plugins.units import unit_conversion_factor


class TestUnitConversionFactor(unittest.TestCase):
    def test_converts_summed_hourly_meters_to_daily_millimeters(self):
        factor = unit_conversion_factor(
            "m/h",
            "mm/d",
            temporal_aggregation="sum",
        )

        self.assertEqual(factor, 1000.0)

    def test_preserves_summed_hourly_millimeters_as_daily_millimeters(self):
        factor = unit_conversion_factor(
            "mm/h",
            "mm/d",
            temporal_aggregation="sum",
        )

        self.assertEqual(factor, 1.0)

    def test_converts_meters_to_millimeters(self):
        factor = unit_conversion_factor("m", "mm")

        self.assertEqual(factor, 1000.0)

    def test_rejects_different_time_bases_without_aggregation(self):
        with self.assertRaisesRegex(ValueError, "without temporal aggregation"):
            unit_conversion_factor("m/h", "mm/d")

    def test_rejects_unsupported_summed_time_bases(self):
        with self.assertRaisesRegex(ValueError, "hourly-to-daily"):
            unit_conversion_factor(
                "m/d",
                "mm/d",
                temporal_aggregation="sum",
            )

    def test_rejects_unsupported_units(self):
        with self.assertRaisesRegex(ValueError, "Unsupported units"):
            unit_conversion_factor("ft/h", "mm/h")


if __name__ == "__main__":
    unittest.main()

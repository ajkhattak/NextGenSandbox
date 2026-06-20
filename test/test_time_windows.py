import unittest

from src.python.context import SandboxContext


class TestSimulationTimeWindows(unittest.TestCase):
    def test_validate_formulation_sets_parsed_model_list(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = "PET,CFE"

        context.validate_formulation()

        self.assertEqual(context.formulation, "PET,CFE,T-ROUTE")
        self.assertEqual(context.formulation_models, ["PET", "CFE", "T-ROUTE"])

    def test_rejects_calibration_eval_time_outside_calibration_time(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.sandbox_config = {
            "simulation": {
                "task_type": "calibration",
                "gage_ids_input": "01109403",
                "calibration_time": {
                    "start_time": "2010-01-01 00:00:00",
                    "end_time": "2010-09-30 23:00:00",
                },
                "calib_eval_time": {
                    "start_time": "2010-10-01 00:00:00",
                    "end_time": "2017-09-30 23:00:00",
                },
            }
        }

        with self.assertRaisesRegex(
            ValueError,
            "calib_eval_time must be within calibration_time",
        ):
            context.load_simulation_config()

    def test_accepts_calibration_eval_time_within_calibration_time(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.sandbox_config = {
            "simulation": {
                "task_type": "calibration",
                "gage_ids_input": "01109403",
                "calibration_time": {
                    "start_time": "2010-01-01 00:00:00",
                    "end_time": "2017-09-30 23:00:00",
                },
                "calib_eval_time": {
                    "start_time": "2010-10-01 00:00:00",
                    "end_time": "2017-09-30 23:00:00",
                },
            }
        }

        context.load_simulation_config()

        self.assertEqual(context.calib_eval_time["start_time"], "2010-10-01 00:00:00")

    def test_rejects_reversed_time_window(self):
        with self.assertRaisesRegex(
            ValueError,
            "start_time must be less than or equal to",
        ):
            SandboxContext.validate_time_window(
                "calibration_time",
                {
                    "start_time": "2017-09-30 23:00:00",
                    "end_time": "2010-01-01 00:00:00",
                },
            )

    def test_rejects_validation_eval_time_outside_validation_time(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.sandbox_config = {
            "simulation": {
                "task_type": "validation",
                "gage_ids_input": "01109403",
                "validation_time": {
                    "start_time": "2018-01-01 00:00:00",
                    "end_time": "2018-09-30 23:00:00",
                },
                "valid_eval_time": {
                    "start_time": "2018-10-01 00:00:00",
                    "end_time": "2019-09-30 23:00:00",
                },
            }
        }

        with self.assertRaisesRegex(
            ValueError,
            "valid_eval_time must be within validation_time",
        ):
            context.load_simulation_config()


if __name__ == "__main__":
    unittest.main()

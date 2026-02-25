import os
import tempfile
import unittest

from sc2.data import Race

from phantom.learn.parameters import (
    MatchupParameterProvider,
    OptimizationTarget,
    ParameterContext,
    Prior,
)


class MatchupParametersTest(unittest.TestCase):
    def test_context_routes_parameter_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = MatchupParameterProvider(pop_size=2, data_path=tmpdir)
            parameter = provider.optimize[OptimizationTarget.CostEfficiency].add("alpha", Prior())

            values = {
                Race.Random: 1.0,
                Race.Terran: 2.0,
                Race.Protoss: 3.0,
                Race.Zerg: 4.0,
            }
            for race, value in values.items():
                provider.manager_for(race).optimize[OptimizationTarget.CostEfficiency].add(
                    "alpha", Prior()
                ).value = value

            provider.set_context(ParameterContext(enemy_race=Race.Random))
            self.assertEqual(parameter.value, 1.0)
            provider.set_context(ParameterContext(enemy_race=Race.Terran))
            self.assertEqual(parameter.value, 2.0)
            provider.set_context(ParameterContext(enemy_race=Race.Protoss))
            self.assertEqual(parameter.value, 3.0)
            provider.set_context(ParameterContext(enemy_race=Race.Zerg))
            self.assertEqual(parameter.value, 4.0)

    def test_save_load_isolated_per_matchup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = MatchupParameterProvider(pop_size=2, data_path=tmpdir)
            provider.optimize[OptimizationTarget.CostEfficiency].add("beta", Prior())

            expected = {
                Race.Random: 11.0,
                Race.Terran: 22.0,
                Race.Protoss: 33.0,
                Race.Zerg: 44.0,
            }
            for race, value in expected.items():
                optimizer = provider.manager_for(race).optimize[OptimizationTarget.CostEfficiency]
                optimizer.get_state()
                assert optimizer._xnes is not None
                optimizer._xnes.loc[0] = value
                provider.save_race(race)

            restored = MatchupParameterProvider(pop_size=2, data_path=tmpdir)
            restored.optimize[OptimizationTarget.CostEfficiency].add("beta", Prior())
            restored.load_all()
            for race, value in expected.items():
                optimizer = restored.manager_for(race).optimize[OptimizationTarget.CostEfficiency]
                optimizer.set_values_from_best()
                parameter = optimizer.add("beta", Prior())
                self.assertEqual(parameter.value, value)

            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "zerg.pkl.xz")))
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "terran.pkl.xz")))
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "protoss.pkl.xz")))
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "random.pkl.xz")))

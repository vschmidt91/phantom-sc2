import lzma
import os
import pickle
import tempfile
import unittest

from sc2.data import Race

from phantom.learn.parameters import (
    MatchupParameterProvider,
    OptimizationTarget,
    ParameterContext,
    ParameterManager,
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

    def test_legacy_fallback_loads_random_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_path = os.path.join(tmpdir, "params.pkl.xz")
            legacy = ParameterManager(pop_size=2)
            optimizer = legacy.optimize[OptimizationTarget.CostEfficiency]
            optimizer.add("legacy", Prior())
            optimizer.get_state()
            assert optimizer._xnes is not None
            optimizer._xnes.loc[0] = 9.0
            with lzma.open(legacy_path, "wb") as handle:
                pickle.dump(legacy.save(), handle)

            provider = MatchupParameterProvider(pop_size=2, data_path=tmpdir, legacy_params_path=legacy_path)
            provider.optimize[OptimizationTarget.CostEfficiency].add("legacy", Prior())
            provider.load_all()

            random_optimizer = provider.manager_for(Race.Random).optimize[OptimizationTarget.CostEfficiency]
            random_optimizer.set_values_from_best()
            random_param = random_optimizer.add("legacy", Prior())
            self.assertEqual(random_param.value, 9.0)

            terran_optimizer = provider.manager_for(Race.Terran).optimize[OptimizationTarget.CostEfficiency]
            terran_optimizer.set_values_from_best()
            terran_param = terran_optimizer.add("legacy", Prior())
            self.assertEqual(terran_param.value, 0.0)

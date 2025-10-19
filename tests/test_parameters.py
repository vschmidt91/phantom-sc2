import unittest

from phantom.parameters import Parameters, Prior


class ParametersTest(unittest.TestCase):
    def setUp(self):
        pass

    def test_evolution(self):
        parameters = Parameters()
        p1 = parameters.add(Prior(0, 1e-3))
        p2 = parameters.add(Prior(1, 1e3))

        parameters.ask()
        self.assertNotEqual(p1.prior.mu, p1.value)
        self.assertNotEqual(p2.prior.mu, p2.value)
        parameters.tell(1)

        parameters.ask()
        parameters.tell(1)
        parameters.ask()
        parameters.tell(1)
        parameters.ask()
        parameters.tell(1)
        parameters.ask()
        parameters.tell(1)
        parameters.ask()
        parameters.tell(1)
        parameters.ask()
        parameters.tell(1)
        parameters.ask()
        parameters.tell(1)
        parameters.ask()
        parameters.tell(1)
        parameters.ask()
        parameters.tell(1)
        parameters.ask()
        parameters.tell(1)
        parameters.ask()
        parameters.tell(1)

    def tearDown(self):
        pass

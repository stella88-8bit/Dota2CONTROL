import unittest
from voice_policy import is_stop_result


class StopPolicyTests(unittest.TestCase):
    def test_explicit_stop(self):
        self.assertTrue(is_stop_result({'text': 'стоп', 'result': [{'word': 'стоп', 'conf': .98}]}))

    def test_noise_partial_or_uncertain_are_not_stop(self):
        for result in [ {'partial': 'стоп'}, {'text': 'непонятная речь'},
                        {'text': 'стоп', 'result': [{'word': 'стоп', 'conf': .5}]},
                        {'text': 'стоп'}, {'text': 'скажи стоп', 'result': [{'word': 'стоп', 'conf': 1}]} ]:
            self.assertFalse(is_stop_result(result))


if __name__ == '__main__': unittest.main()

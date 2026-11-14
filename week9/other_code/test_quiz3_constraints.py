"""LMFE 0.11.3 character-token regression tests; no Qwen weights or torch required."""
import json
import unittest

from .quiz3 import FACTS_DECODING_SCHEMA
from .test_quiz3 import complete


class ConstraintTests(unittest.TestCase):
    def setup_parser(self, sample):
        try:
            from lmformatenforcer import JsonSchemaParser
            from lmformatenforcer.tokenenforcer import TokenEnforcer, TokenEnforcerTokenizerData
        except ImportError:
            self.skipTest("lm-format-enforcer未安裝")
        chars = sorted(set(sample + " 好的詩\t\n"))
        ids = {char: i + 1 for i, char in enumerate(chars)}
        chars_by_id = {i: char for char, i in ids.items()}
        data = TokenEnforcerTokenizerData(
            [(i, char, False) for i, char in chars_by_id.items()],
            lambda tokens: "".join(chars_by_id.get(i, "") for i in tokens),
            0, False, len(chars) + 1,
        )
        parser = JsonSchemaParser(FACTS_DECODING_SCHEMA)
        enforcer = TokenEnforcer(data, parser)
        parser.config.max_consecutive_whitespaces = 2
        return enforcer, ids

    def check_sample(self, value):
        sample = json.dumps(value, ensure_ascii=False)
        enforcer, ids = self.setup_parser(sample)
        tokens = [999999]  # Stand-in for prompt prefix; excluded by TokenEnforcer.
        self.assertNotIn(ids["好"], enforcer.get_allowed_tokens(tokens).allowed_tokens)
        for char in sample:
            allowed = enforcer.get_allowed_tokens(tokens).allowed_tokens
            self.assertIn(ids[char], allowed)
            self.assertNotIn(0, allowed, "完整JSON之前不可EOS")
            tokens.append(ids[char])
        self.assertIn(0, enforcer.get_allowed_tokens(tokens).allowed_tokens)

    def test_cjk_text_and_department(self):
        self.check_sample(complete())

    def test_null_department_and_unknown_fields(self):
        self.check_sample(complete(product=None, department=None, order_id=None))

    def test_repeated_whitespace_is_bounded(self):
        sample = json.dumps(complete(), ensure_ascii=False)
        enforcer, ids = self.setup_parser(sample)
        tokens = [999999]
        for _ in range(2):
            self.assertIn(ids[" "], enforcer.get_allowed_tokens(tokens).allowed_tokens)
            tokens.append(ids[" "])
        self.assertNotIn(ids[" "], enforcer.get_allowed_tokens(tokens).allowed_tokens)


if __name__ == "__main__":
    unittest.main()

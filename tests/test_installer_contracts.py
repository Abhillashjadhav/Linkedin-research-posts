from __future__ import annotations

import inspect
import unittest

from authority_os import v1_completion, v1_gates


def _assert_signature_compatible(
    test: unittest.TestCase,
    original,
    replacement,
    dotted_name: str,
) -> None:
    original_parameters = inspect.signature(original).parameters
    replacement_parameters = inspect.signature(replacement).parameters
    replacement_var_positional = any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in replacement_parameters.values()
    )
    replacement_var_keyword = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in replacement_parameters.values()
    )

    for name, original_parameter in original_parameters.items():
        replacement_parameter = replacement_parameters.get(name)
        message = f"{dotted_name}: replacement lost parameter {name!r}"
        if original_parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            test.assertTrue(replacement_var_positional, message)
            continue
        if original_parameter.kind == inspect.Parameter.VAR_KEYWORD:
            test.assertTrue(replacement_var_keyword, message)
            continue
        if original_parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
            test.assertTrue(
                replacement_parameter is not None
                and replacement_parameter.kind == inspect.Parameter.POSITIONAL_ONLY
                or replacement_var_positional,
                message,
            )
        elif original_parameter.kind == inspect.Parameter.KEYWORD_ONLY:
            test.assertIsNotNone(replacement_parameter, message)
            test.assertEqual(
                replacement_parameter.kind,
                inspect.Parameter.KEYWORD_ONLY,
                f"{dotted_name}: keyword-only parameter {name!r} changed kind",
            )
        else:
            explicit_match = (
                replacement_parameter is not None
                and replacement_parameter.kind
                == inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
            test.assertTrue(
                explicit_match
                or (replacement_var_positional and replacement_var_keyword),
                message,
            )

        if (
            original_parameter.default is not inspect.Parameter.empty
            and replacement_parameter is not None
        ):
            test.assertIsNot(
                replacement_parameter.default,
                inspect.Parameter.empty,
                f"{dotted_name}: optional parameter {name!r} became required",
            )

    for name, replacement_parameter in replacement_parameters.items():
        if name in original_parameters or replacement_parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        test.assertIsNot(
            replacement_parameter.default,
            inspect.Parameter.empty,
            f"{dotted_name}: replacement added required parameter {name!r}",
        )


class InstallerContractTests(unittest.TestCase):
    def test_every_installed_callable_preserves_its_original_signature(self) -> None:
        pairs = (*v1_gates.INSTALLED_PAIRS, *v1_completion.INSTALLED_PAIRS)
        for original, replacement, dotted_name in pairs:
            with self.subTest(target=dotted_name):
                _assert_signature_compatible(
                    self,
                    original,
                    replacement,
                    dotted_name,
                )


if __name__ == "__main__":
    unittest.main()

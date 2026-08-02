import pytest
from pydantic import ValidationError

from context_router.schemas.runtime_configs import RuntimeConfigModeUpdate


def test_runtime_config_rejects_invalid_yaml_with_file_and_line() -> None:
    with pytest.raises(ValidationError, match=r"compose\.yml.*第 5 行"):
        RuntimeConfigModeUpdate.model_validate(
            {
                "files": [
                    {
                        "relative_path": "compose.yml",
                        "content": (
                            "services:\n"
                            "  app:\n"
                            "    command: |-\n"
                            "    echo broken\n"
                            "next: value\n"
                        ),
                    }
                ]
            }
        )


def test_runtime_config_accepts_valid_yaml_literal_block_and_non_yaml() -> None:
    update = RuntimeConfigModeUpdate.model_validate(
        {
            "files": [
                {
                    "relative_path": "compose.yml",
                    "content": (
                        "services:\n  app:\n    command: |-\n      echo valid\n"
                    ),
                },
                {
                    "relative_path": "deploy.sh",
                    "content": "not: [required to be yaml\n",
                    "executable": True,
                },
            ]
        }
    )

    assert [item.relative_path for item in update.files] == [
        "compose.yml",
        "deploy.sh",
    ]

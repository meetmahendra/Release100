# Copyright 2026 Mahendra GURAV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Unit tests for the Live Provider API Key Validation Service (core_platform/app/llm/validator.py).
"""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch
import pytest

from core_platform.app.llm.validator import validate_provider_api_key


def test_empty_api_key_returns_invalid() -> None:
    valid, msg = validate_provider_api_key("gemini", "")
    assert valid is False
    assert "cannot be empty" in msg


def test_synthetic_test_key_bypass() -> None:
    valid, msg = validate_provider_api_key("gemini", "mock_gemini_test_key_12345")
    assert valid is True
    assert "Synthetic" in msg

    valid_oa, msg_oa = validate_provider_api_key("openai", "test_openai_key_67890")
    assert valid_oa is True
    assert "Synthetic" in msg_oa


@patch("urllib.request.urlopen")
def test_gemini_validation_success(mock_urlopen: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    valid, msg = validate_provider_api_key("gemini", "some_actual_looking_key_9999")
    assert valid is True
    assert "verified with Google Gemini" in msg


@patch("urllib.request.urlopen")
def test_gemini_validation_http_error(mock_urlopen: MagicMock) -> None:
    error_body = json.dumps({"error": {"message": "API_KEY_INVALID"}}).encode("utf-8")
    fp = io.BytesIO(error_body)
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="https://generativelanguage.googleapis.com",
        code=400,
        msg="Bad Request",
        hdrs=None,  # type: ignore[arg-type]
        fp=fp,
    )

    valid, msg = validate_provider_api_key("gemini", "invalid_key_1234567890")
    assert valid is False
    assert "API_KEY_INVALID" in msg


@patch("urllib.request.urlopen")
def test_openai_validation_success(mock_urlopen: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    valid, msg = validate_provider_api_key("openai", "live_openai_key_abcdef")
    assert valid is True
    assert "verified with OpenAI" in msg


@patch("urllib.request.urlopen")
def test_openai_validation_http_error(mock_urlopen: MagicMock) -> None:
    error_body = json.dumps({"error": {"message": "Incorrect API key provided"}}).encode("utf-8")
    fp = io.BytesIO(error_body)
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="https://api.openai.com",
        code=401,
        msg="Unauthorized",
        hdrs=None,  # type: ignore[arg-type]
        fp=fp,
    )

    valid, msg = validate_provider_api_key("openai", "invalid_openai_key_abcdef")
    assert valid is False
    assert "Incorrect API key" in msg


def test_whatsapp_token_validation() -> None:
    valid, msg = validate_provider_api_key("whatsapp", "EAAtesttokenlongenough12345")
    assert valid is True

    invalid, bad_msg = validate_provider_api_key("whatsapp", "short")
    assert invalid is False
    assert "too short" in bad_msg


def test_unsupported_provider() -> None:
    valid, msg = validate_provider_api_key("unsupported_provider_xyz", "some_key_12345")
    assert valid is False
    assert "Unsupported provider" in msg

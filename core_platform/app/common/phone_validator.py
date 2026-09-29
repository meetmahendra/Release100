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
E.164 Universal Phone Number Sanitization & Country Code Normalizer.

Enforces strict E.164 compliance across the platform:
- Defaults 10-digit subscriber numbers to Indian country code (+91).
- Auto-prepends '+' to country-coded numbers entered without prefix (e.g. 918087545430 -> +918087545430).
- Strips leading trunk prefixes (e.g. 08087545430 -> +918087545430).
- Preserves valid international E.164 numbers (e.g. +14155552671).
"""

import re
from typing import Optional


def normalize_phone_number(raw_phone: str, default_country_code: str = "+91") -> str:
    """Normalize arbitrary phone number input into strict E.164 international format.

    Args:
        raw_phone: Raw phone string (e.g., '8087545430', '918087545430', '+91 80875-45430').
        default_country_code: Country code prefix to apply if none provided. Default is '+91'.

    Returns:
        Standardized E.164 string starting with '+' (e.g. '+918087545430').

    Raises:
        ValueError: If input contains no digits or cannot be converted to a valid phone format.
    """
    if not raw_phone:
        raise ValueError("Phone number cannot be empty")

    cleaned = str(raw_phone).strip()
    has_plus = cleaned.startswith("+")

    # Keep only digits
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        raise ValueError(f"Phone number '{raw_phone}' contains no digits")

    # Case 1: Already had leading '+'
    if has_plus:
        if len(digits) < 7 or len(digits) > 15:
            raise ValueError(f"Invalid international phone number length (+{digits})")
        return f"+{digits}"

    # Case 2: 11 digits starting with trunk 0 (e.g. 08087545430)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]  # Becomes 10 digits

    # Case 3: 10 digits (Standard Indian national mobile)
    if len(digits) == 10:
        cc = default_country_code if default_country_code.startswith("+") else f"+{default_country_code}"
        return f"{cc}{digits}"

    # Case 4: 12 digits starting with '91' (Country code entered without '+')
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"

    # Case 5: 11 to 15 digits entered without '+'
    if 11 <= len(digits) <= 15:
        return f"+{digits}"

    raise ValueError(f"Phone number '{raw_phone}' is not a recognized mobile format")


def is_valid_phone_number(raw_phone: Optional[str]) -> bool:
    """Check whether a given phone string can be normalized to a valid E.164 format."""
    if not raw_phone:
        return False
    try:
        normalized = normalize_phone_number(raw_phone)
        return bool(re.match(r"^\+[1-9]\d{9,14}$", normalized))
    except Exception:
        return False

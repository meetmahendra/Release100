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

"""Synthetic Unit Tests for FaceRecognizerSkill."""

import numpy as np
import pytest
from core_platform.app.skills.face_recognizer import FaceRecognizerSkill


@pytest.mark.asyncio
async def test_face_recognizer_initialization() -> None:
    """FaceRecognizerSkill must initialize and declare commercial compliance."""
    skill = FaceRecognizerSkill()
    await skill.ensure_initialized()
    assert skill.is_available() is True
    health = skill.get_health_status()
    assert health["commercial_license_compliant"] is True
    assert health["encryption"] == "AES-256-GCM"


@pytest.mark.asyncio
async def test_face_recognizer_cosine_similarity() -> None:
    """Cosine similarity must return 1.0 for identical vectors and 0.0 for orthogonal."""
    skill = FaceRecognizerSkill()
    vec_a = np.zeros(512, dtype=np.float32)
    vec_a[0] = 1.0

    vec_b = np.zeros(512, dtype=np.float32)
    vec_b[0] = 1.0

    vec_c = np.zeros(512, dtype=np.float32)
    vec_c[1] = 1.0

    assert skill.compute_cosine_similarity(vec_a, vec_b) == pytest.approx(1.0, abs=1e-5)
    assert skill.compute_cosine_similarity(vec_a, vec_c) == pytest.approx(0.0, abs=1e-5)


@pytest.mark.asyncio
async def test_face_recognizer_aes256_encryption_at_rest() -> None:
    """Biometric vectors must encrypt and decrypt perfectly via AES-256-GCM."""
    skill = FaceRecognizerSkill()
    original_vec = np.random.randn(512).astype(np.float32)
    original_vec = original_vec / np.linalg.norm(original_vec)

    encrypted_b64 = skill.encrypt_embedding(original_vec)
    assert isinstance(encrypted_b64, str)
    assert len(encrypted_b64) > 100

    decrypted_vec = skill.decrypt_embedding(encrypted_b64)
    np.testing.assert_allclose(original_vec, decrypted_vec, rtol=1e-5, atol=1e-5)


@pytest.mark.asyncio
async def test_face_recognizer_compute_embedding_mock() -> None:
    """Mock vectors must normalize and extract cleanly."""
    skill = FaceRecognizerSkill()
    mock_payload = {"mock_vector": [1.0] * 512}

    success, vec, msg = await skill.compute_embedding(mock_payload)
    assert success is True
    assert vec is not None
    assert vec.shape == (512,)
    assert np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-5)


@pytest.mark.asyncio
async def test_face_recognizer_image_hygiene() -> None:
    """Hygiene check must reject empty payloads."""
    skill = FaceRecognizerSkill()
    passed, reason = await skill.check_image_hygiene(b"tiny")
    assert passed is False
    assert "empty or corrupted" in reason

    valid_dummy_bytes = b"header" + b"X" * 1000
    passed_valid, _ = await skill.check_image_hygiene(valid_dummy_bytes)
    assert passed_valid is True


@pytest.mark.anyio
async def test_face_recognizer_numpy_array_input() -> None:
    """FaceRecognizerSkill must extract embedding from 3D numpy array."""
    skill = FaceRecognizerSkill()
    arr = np.random.randint(0, 255, (120, 120, 3), dtype=np.uint8)
    success, vec, msg = await skill.compute_embedding(arr)
    assert success is True
    assert vec is not None
    assert vec.shape == (512,)

    # Invalid input type
    success_bad, vec_bad, msg_bad = await skill.compute_embedding(12345)
    assert success_bad is False
    assert vec_bad is None


@pytest.mark.anyio
async def test_face_recognizer_2d_numpy_and_hygiene() -> None:
    """Test 2D grayscale array embedding and hygiene boundary checks."""
    import io
    from PIL import Image

    skill = FaceRecognizerSkill()

    # 1. 2D NumPy array
    arr_2d = np.zeros((64, 64), dtype=np.uint8)
    ok_2d, vec_2d, _ = await skill.compute_embedding(arr_2d)
    assert ok_2d is True
    assert vec_2d is not None
    assert vec_2d.shape == (512,)

    # 2. Hygiene check: oversized image (> 15MB)
    passed_oversized, reason_ov = await skill.check_image_hygiene(b"X" * (16 * 1024 * 1024))
    assert passed_oversized is False
    assert "maximum allowed size" in reason_ov

    # 3. Hygiene check: resolution too low (< 32x32)
    img_low = Image.new("RGB", (20, 20), color=(100, 100, 100))
    buf_low = io.BytesIO()
    img_low.save(buf_low, format="JPEG")
    passed_low, reason_low = await skill.check_image_hygiene(buf_low.getvalue())
    assert passed_low is False
    assert "resolution too low" in reason_low

    # 4. Hygiene check: blank / low contrast
    img_blank = Image.new("RGB", (64, 64), color=(0, 0, 0))
    buf_blank = io.BytesIO()
    img_blank.save(buf_blank, format="JPEG")
    passed_blank, reason_blank = await skill.check_image_hygiene(buf_blank.getvalue())
    assert passed_blank is False
    assert "lacks contrast" in reason_blank



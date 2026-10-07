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

"""GEES v1.0 Deep Coverage Tests for Configuration Backup, Verifier, and Biometrics."""

import io
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
import numpy as np
from PIL import Image, ImageDraw
import pytest

from core_platform.app.diagnostics.config_backup import (
    create_backup,
    list_backups,
    restore_backup,
    save_master_config,
    read_env_dict,
)
from core_platform.app.diagnostics.verifier import (
    _is_placeholder,
    verify_ports,
    verify_hmac_secret,
)
from core_platform.app.skills.face_recognizer import (
    FaceRecognizerSkill,
    _extract_hog_512_embedding,
    _normalize_face_crop,
)


# ============================================================================
# 1. Config Backup & Rollback Tests
# ============================================================================

def test_config_backup_and_restore_cycle() -> None:
    """Test creating .env backups, listing snapshots, and rollback."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        env_file = root / ".env"
        env_file.write_text("# Initial Configuration\nKIOSK_ID=NODE-PUNE-04\nPORT=8002\n", encoding="utf-8")
        backup_dir = root / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 1. Create backup
        with patch("core_platform.app.diagnostics.config_backup.get_backup_dir", return_value=backup_dir):
            bak_path = create_backup(env_path=env_file)
            assert bak_path is not None
            assert bak_path.exists()

            # 2. List backups
            backups = list_backups(backup_dir=backup_dir)
            assert len(backups) == 1
            assert backups[0]["filename"] == bak_path.name

            # 3. Read env dict
            ed = read_env_dict(env_path=env_file)
            assert ed.get("KIOSK_ID") == "NODE-PUNE-04"

            # 4. Save master config
            updates = {"PORT": "9000", "NEW_VAR": "TEST_VAL"}
            ok_save, _ = save_master_config(updates=updates, env_path=env_file)
            assert ok_save is True
            content = env_file.read_text(encoding="utf-8")
            assert "PORT=9000" in content
            assert "# Initial Configuration" in content
            assert "NEW_VAR=TEST_VAL" in content

            # 5. Restore backup
            restored, msg = restore_backup(filename=bak_path.name, env_path=env_file)
            assert restored is True
            restored_content = env_file.read_text(encoding="utf-8")
            assert "PORT=8002" in restored_content


# ============================================================================
# 2. Verifier Helper Tests
# ============================================================================

def test_verifier_helpers() -> None:
    """Test credential placeholder validation and local port inspection."""
    # 1. Placeholder detection
    assert _is_placeholder(None) is True
    assert _is_placeholder("") is True
    assert _is_placeholder("your_api_key_here") is True
    assert _is_placeholder("none") is True
    assert _is_placeholder("valid_prod_api_key_sample_12345") is False

    # 2. Local port verification (mocked socket)
    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0
        mock_sock_cls.return_value = mock_sock
        res_ports = verify_ports([8002])
        assert isinstance(res_ports, dict)

    # 3. HMAC secret verification
    res_hmac = verify_hmac_secret("0123456789abcdef0123456789abcdef")
    assert res_hmac["status"] in ("ok", "CONFIGURED")


# ============================================================================
# 3. Biometric Crop & HOG Extraction Edge Branches
# ============================================================================

def test_face_crop_and_hog_extraction_edge_cases() -> None:
    """Test crop normalization and HOG 512 embedding extraction on edge arrays."""
    # 1. Blank/flat image normalization
    flat_img = Image.new("RGB", (100, 100), color=(128, 128, 128))
    norm_crop = _normalize_face_crop(flat_img)
    assert norm_crop.size == (100, 100)

    # 2. HOG extraction on patterned PIL
    gray_pil = Image.new("L", (112, 112), color=(50,))
    draw = ImageDraw.Draw(gray_pil)
    draw.rectangle((20, 20, 80, 80), fill=200)
    vec = _extract_hog_512_embedding(gray_pil)
    assert isinstance(vec, np.ndarray)
    assert vec.shape == (512,)
    assert np.isclose(float(np.linalg.norm(vec)), 1.0)

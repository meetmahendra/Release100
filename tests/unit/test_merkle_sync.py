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
Unit Tests for Cryptographic Merkle Tree Reconciler.

Adheres strictly to GEES v2.0 Dual-Engine Verification Regime (Engine A).
"""

import pytest

from core_platform.app.sync.merkle_reconciler import EMPTY_TREE_HASH, MerkleTree


def test_merkle_hash_record_determinism() -> None:
    """Verify hash_record generates identical SHA-256 regardless of dict key insertion order."""
    rec1 = {"id": "1", "temp": 3.4, "kiosk": "K-01"}
    rec2 = {"kiosk": "K-01", "id": "1", "temp": 3.4}
    assert MerkleTree.hash_record(rec1) == MerkleTree.hash_record(rec2)


def test_merkle_tree_empty() -> None:
    """Verify empty MerkleTree returns EMPTY_TREE_HASH."""
    tree = MerkleTree([])
    assert tree.get_root_hash() == EMPTY_TREE_HASH
    assert tree.find_divergent_leaf_indices(MerkleTree([])) == []


def test_merkle_tree_root_equality_and_divergence() -> None:
    """Verify root hash matching and difference detection."""
    records_a = [
        {"seq": 1, "action": "CHECKIN", "emp": "EMP-01"},
        {"seq": 2, "action": "TEMP_LOG", "temp": 3.2},
        {"seq": 3, "action": "TEMP_LOG", "temp": 3.5},
    ]
    records_b = list(records_a)

    tree_a = MerkleTree.from_records(records_a)
    tree_b = MerkleTree.from_records(records_b)

    assert tree_a.get_root_hash() == tree_b.get_root_hash()
    assert tree_a.find_divergent_leaf_indices(tree_b) == []

    # Modify single record in records_b
    records_b[1] = {"seq": 2, "action": "TEMP_LOG", "temp": 9.9}
    tree_b_modified = MerkleTree.from_records(records_b)

    assert tree_a.get_root_hash() != tree_b_modified.get_root_hash()
    divergent = tree_a.find_divergent_leaf_indices(tree_b_modified)
    assert divergent == [1]


def test_merkle_tree_odd_number_of_leaves() -> None:
    """Verify Merkle tree construction with odd number of leaves."""
    records = [
        {"id": "a"},
        {"id": "b"},
        {"id": "c"},
    ]
    tree = MerkleTree.from_records(records)
    assert tree.root is not None
    assert len(tree.get_root_hash()) == 64

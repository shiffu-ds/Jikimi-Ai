import json
import math
from datetime import UTC, datetime
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jikimi_crypto import (
    Signer,
    canonicalize,
    generate_private_key,
    inclusion_proof,
    json_digest,
    merkle_root,
    sha256_file,
    sha256_hex,
    verify_inclusion,
    verify_json,
)
from jikimi_crypto.canonical_json import _es6_number
from jikimi_crypto.signing import load_private_key, save_private_key


class TestCanonicalJson:
    def test_sorted_compact_utf8(self) -> None:
        assert canonicalize({"b": 1, "a": "کالی", "c": [True, None]}) == '{"a":"کالی","b":1,"c":[true,null]}'.encode()

    def test_key_order_does_not_matter(self) -> None:
        assert canonicalize({"x": 1, "y": {"b": 2, "a": 1}}) == canonicalize({"y": {"a": 1, "b": 2}, "x": 1})

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1.0, "1"),
            (0.5, "0.5"),
            (0.004, "0.004"),
            (1e-7, "1e-7"),
            (1e-6, "0.000001"),
            (123.456, "123.456"),
            (-2.5, "-2.5"),
            (1e21, "1e+21"),
            (1.5e21, "1.5e+21"),
            (1e20, "100000000000000000000"),
            (0.1 + 0.2, "0.30000000000000004"),
        ],
    )
    def test_es6_numbers(self, value: float, expected: str) -> None:
        assert _es6_number(value) == expected

    def test_rejects_nan_and_naive_datetimes(self) -> None:
        with pytest.raises(ValueError):
            canonicalize({"x": math.nan})
        with pytest.raises(ValueError):
            canonicalize({"t": datetime(2026, 1, 1)})

    def test_types_are_normalized(self) -> None:
        u = UUID("0192f3a4-7c1e-7b2a-9f10-3c5d6e7f8a90")
        out = canonicalize({"id": u, "at": datetime(2026, 10, 23, 18, 0, tzinfo=UTC)})
        assert out == b'{"at":"2026-10-23T18:00:00+00:00","id":"0192f3a4-7c1e-7b2a-9f10-3c5d6e7f8a90"}'

    @given(
        st.recursive(
            st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | st.text(),
            lambda children: (
                st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=5), children, max_size=4)
            ),
            max_leaves=12,
        )
    )
    def test_roundtrip_is_value_preserving(self, obj: object) -> None:
        # canonical bytes must parse back to an equal value (floats compare numerically)
        assert json.loads(canonicalize(obj)) == obj


class TestSigning:
    def test_sign_and_verify_json(self) -> None:
        signer = Signer.from_key(generate_private_key())
        payload = {"alert_id": "x", "score": 0.81}
        sig = signer.sign(payload)
        assert verify_json(signer.public_key, payload, sig)
        assert verify_json(signer.public_key, {"score": 0.81, "alert_id": "x"}, sig)  # order-free

    def test_one_change_breaks_signature(self) -> None:
        signer = Signer.from_key(generate_private_key())
        sig = signer.sign({"score": 0.81})
        assert not verify_json(signer.public_key, {"score": 0.82}, sig)
        other = Signer.from_key(generate_private_key())
        assert not verify_json(other.public_key, {"score": 0.81}, sig)
        assert not verify_json(signer.public_key, {"score": 0.81}, "bm90LWEtc2ln")
        assert not verify_json(signer.public_key, {"score": 0.81}, None)

    def test_key_file_is_private(self, tmp_path) -> None:
        key = generate_private_key()
        path = tmp_path / "keys" / "device.key"
        save_private_key(key, path, passphrase=b"pw")
        assert (path.stat().st_mode & 0o777) == 0o600
        loaded = load_private_key(path, passphrase=b"pw")
        assert Signer.from_key(loaded).key_id == Signer.from_key(key).key_id
        assert Signer.from_key(key).key_id.startswith("ed25519:")


class TestMerkle:
    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 8, 13, 33])
    def test_every_leaf_has_valid_proof(self, n: int) -> None:
        leaves = [json_digest({"i": i}) for i in range(n)]
        root = merkle_root(leaves)
        for i, leaf in enumerate(leaves):
            assert verify_inclusion(leaf, inclusion_proof(leaves, i), root)

    def test_tampered_leaf_fails(self) -> None:
        leaves = [json_digest({"i": i}) for i in range(6)]
        root = merkle_root(leaves)
        proof = inclusion_proof(leaves, 2)
        assert not verify_inclusion(json_digest({"i": 99}), proof, root)
        assert not verify_inclusion(leaves[3], proof, root)

    def test_rfc6962_vectors(self) -> None:
        # empty tree hash and single-leaf hash as defined in RFC 6962 section 2.1
        assert merkle_root([]).hex() == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert merkle_root([b""]).hex() == "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d"


def test_sha256_file_streams(tmp_path) -> None:
    data = b"x" * (3 * 1024 * 1024 + 17)
    p = tmp_path / "clip.bin"
    p.write_bytes(data)
    assert sha256_file(p) == sha256_hex(data)
    data2 = bytearray(data)
    data2[1_000_000] ^= 0x01  # flip one bit
    p.write_bytes(bytes(data2))
    assert sha256_file(p) != sha256_hex(data)

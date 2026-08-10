from reva_core.security.local_token import ensure_local_token, token_path_for


def test_ensure_local_token_generates_high_entropy_token(tmp_path):
    token = ensure_local_token(tmp_path)
    assert len(token) >= 32


def test_ensure_local_token_persists_to_file(tmp_path):
    token = ensure_local_token(tmp_path)
    path = token_path_for(tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip() == token


def test_ensure_local_token_is_idempotent_across_calls(tmp_path):
    first = ensure_local_token(tmp_path)
    second = ensure_local_token(tmp_path)
    assert first == second


def test_ensure_local_token_creates_data_dir_if_missing(tmp_path):
    nested = tmp_path / "nested" / "data"
    assert not nested.exists()
    ensure_local_token(nested)
    assert nested.exists()


def test_two_different_data_dirs_get_different_tokens(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    token_a = ensure_local_token(dir_a)
    token_b = ensure_local_token(dir_b)
    assert token_a != token_b

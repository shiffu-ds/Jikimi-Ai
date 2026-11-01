"""Talks to the Jikimi API on behalf of the signed-in person (Bearer token kept in the session)."""

from __future__ import annotations

import contextlib
import os
from typing import Any

import httpx
import streamlit as st

BASE = os.environ.get("JIKIMI_API_URL", "http://127.0.0.1:8000").rstrip("/")


class ApiError(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None) -> None:
        super().__init__(f"{title}: {detail}" if detail else title)
        self.status, self.title, self.detail = status, title, detail


def _headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/json", "X-Jikimi-Client": "console"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _check(r: httpx.Response) -> Any:
    if r.status_code == 204:
        return None
    try:
        data = r.json() if r.content else None
    except ValueError:
        data = None
    if r.status_code >= 400:
        if r.status_code == 401:
            st.session_state.pop("token", None)
        title = (data or {}).get("title") if isinstance(data, dict) else None
        detail = (data or {}).get("detail") if isinstance(data, dict) else None
        raise ApiError(r.status_code, title or r.reason_phrase, detail if isinstance(detail, str) else None)
    return data


def token() -> str | None:
    return st.session_state.get("token")


@st.cache_data(ttl=4, show_spinner=False)
def _cached_get(path: str, params: tuple[tuple[str, Any], ...], tok: str | None) -> Any:
    with httpx.Client(base_url=BASE, timeout=20) as c:
        return _check(c.get(path, params=list(params), headers=_headers(tok)))


def get(path: str, fresh: bool = False, **params: Any) -> Any:
    flat: list[tuple[str, Any]] = []
    for k, v in params.items():
        if v is None or v == "" or v == []:
            continue
        flat.extend((k, x) for x in v) if isinstance(v, list | tuple) else flat.append((k, v))
    if fresh:
        _cached_get.clear()
    return _cached_get(path, tuple(flat), token())


def post(
    path: str,
    body: Any = None,
    *,
    raw: bytes | None = None,
    content_type: str | None = None,
    method: str = "POST",
    **params: Any,
) -> Any:
    headers = _headers(token())
    with httpx.Client(base_url=BASE, timeout=120) as c:
        if raw is not None:
            headers["Content-Type"] = content_type or "application/octet-stream"
            r = c.request(method, path, content=raw, headers=headers, params=params or None)
        else:
            r = c.request(method, path, json=body, headers=headers, params=params or None)
    _cached_get.clear()
    return _check(r)


@st.cache_data(ttl=3, show_spinner=False)
def media(path: str, tok: str | None) -> bytes | None:
    """A clip, keyframe, snapshot or thumbnail (they need the same sign-in as the API)."""
    if not path:
        return None
    with httpx.Client(base_url=BASE, timeout=30) as c:
        r = c.get(path, headers=_headers(tok))
    return r.content if r.status_code == 200 else None


def login(username: str, password: str) -> dict[str, Any]:
    with httpx.Client(base_url=BASE, timeout=20) as c:
        data = _check(
            c.post("/v1/auth/login", json={"username": username, "password": password}, headers=_headers(None))
        )
    st.session_state["token"] = data["token"]
    st.session_state["user"] = data["user"]
    return data


def logout() -> None:
    with contextlib.suppress(Exception):  # the session ends here either way
        post("/v1/auth/logout")
    for k in list(st.session_state):
        del st.session_state[k]

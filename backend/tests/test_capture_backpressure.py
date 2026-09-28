import pytest

from context_router.schemas.interface_forwarding import InterfaceForwardingBrowserCaptureImport
from context_router.services.interface_forwarding import (
    _BROWSER_IMPORT_SLOTS,
    InterfaceForwardingError,
    InterfaceForwardingService,
)


def test_busy_import_rejects_without_opening_database():
    service = InterfaceForwardingService(None)
    payload = InterfaceForwardingBrowserCaptureImport(
        workspace_id="test",
        environment_key="local",
        captures=[{"url": "http://localhost/read", "method": "GET"}],
    )
    assert _BROWSER_IMPORT_SLOTS.acquire(False)
    assert _BROWSER_IMPORT_SLOTS.acquire(False)
    try:
        with pytest.raises(InterfaceForwardingError, match="繁忙"):
            service.import_browser_captures(payload)
    finally:
        _BROWSER_IMPORT_SLOTS.release()
        _BROWSER_IMPORT_SLOTS.release()
    with pytest.raises(InterfaceForwardingError, match="数据库"):
        service.import_browser_captures(payload)
    assert _BROWSER_IMPORT_SLOTS.acquire(False)
    assert _BROWSER_IMPORT_SLOTS.acquire(False)
    _BROWSER_IMPORT_SLOTS.release()
    _BROWSER_IMPORT_SLOTS.release()


@pytest.mark.parametrize(
    "template,path,expected",
    [
        ("/page", "/page", True),
        ("/page", "/page/1", False),
        ("/item/{id}", "/item/1", True),
        ("/item/{id}", "/item/1/2", False),
        ("/x.a", "/x-a", False),
        ("/{id}.json", "/1.json", True),
    ],
)
def test_cached_match_preserves_template_semantics(template, path, expected):
    assert InterfaceForwardingService._path_template_matches(template, path) == expected

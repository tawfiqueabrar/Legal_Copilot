from app.main import app


def test_session_routes_are_registered():
    paths = app.openapi()["paths"]
    assert "post" in paths["/sessions"]
    assert "post" in paths["/sessions/{session_id}/analyze"]
    assert "get" in paths["/sessions/{session_id}/memo"]
    assert "get" in paths["/sessions/{session_id}/memo.docx"]
    assert "get" in paths["/sessions/{session_id}/memo.pdf"]
    assert "delete" in paths["/sessions/{session_id}"]

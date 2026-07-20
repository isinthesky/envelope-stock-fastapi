from src.main import app


def test_api_documentation_routes_are_disabled_in_all_environments() -> None:
    """Keep the documented no-exposure policy aligned with the FastAPI configuration."""
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None

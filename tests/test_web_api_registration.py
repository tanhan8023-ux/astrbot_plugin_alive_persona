import ast
from pathlib import Path


def test_web_api_registration_uses_astrbot_view_handler_keyword():
    main_path = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    registrations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_web_api"
    ]

    assert len(registrations) == 3
    for call in registrations:
        keywords = {item.arg for item in call.keywords}
        assert "view_handler" in keywords
        assert "handler" not in keywords
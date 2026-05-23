"""Eval case: Add a feature to an existing Python Flask app.

Tests whether the agent integrates a new feature into existing route handlers
and models rather than creating a standalone new app.
"""

CASE = {
    "name": "add-search-filter",
    "description": "Add search/filter to existing products list endpoint",
    "issue": {
        "title": "Add search and filter to GET /products",
        "description": (
            "Add query parameter support to the existing GET /products endpoint: "
            "?q=searchterm for full-text search on name/description, and "
            "?category=electronics for category filtering. Both should be optional "
            "and combinable."
        ),
        "issue_type": "feature",
        "has_ui": False,
    },
    "repo_tree": [
        "requirements.txt",
        "app/__init__.py",
        "app/models.py",
        "app/routes/__init__.py",
        "app/routes/products.py",
        "app/routes/categories.py",
        "app/db.py",
        "tests/__init__.py",
        "tests/conftest.py",
        "tests/test_products.py",
        "tests/test_categories.py",
    ],
    "repo_files": {
        "requirements.txt": "flask==3.0\nsqlalchemy==2.0\npytest==8.0\npytest-flask==1.3\n",
        "app/routes/products.py": (
            'from flask import Blueprint, jsonify\n'
            'from app.models import Product\n'
            'from app.db import db\n'
            '\n'
            'bp = Blueprint("products", __name__, url_prefix="/products")\n'
            '\n'
            '\n'
            '@bp.route("/")\n'
            'def list_products():\n'
            '    products = db.session.query(Product).all()\n'
            '    return jsonify([p.to_dict() for p in products])\n'
            '\n'
            '\n'
            '@bp.route("/<int:product_id>")\n'
            'def get_product(product_id):\n'
            '    product = db.session.get(Product, product_id)\n'
            '    if not product:\n'
            '        return jsonify({"error": "not found"}), 404\n'
            '    return jsonify(product.to_dict())\n'
        ),
        "app/models.py": (
            'from app.db import db\n'
            '\n'
            '\n'
            'class Product(db.Model):\n'
            '    __tablename__ = "products"\n'
            '    id = db.Column(db.Integer, primary_key=True)\n'
            '    name = db.Column(db.String(200), nullable=False)\n'
            '    description = db.Column(db.Text)\n'
            '    category = db.Column(db.String(100))\n'
            '    price = db.Column(db.Float)\n'
            '\n'
            '    def to_dict(self):\n'
            '        return {\n'
            '            "id": self.id,\n'
            '            "name": self.name,\n'
            '            "description": self.description,\n'
            '            "category": self.category,\n'
            '            "price": self.price,\n'
            '        }\n'
        ),
        "tests/conftest.py": (
            'import pytest\n'
            'from app import create_app\n'
            'from app.db import db as _db\n'
            '\n'
            '\n'
            '@pytest.fixture\n'
            'def app():\n'
            '    app = create_app(testing=True)\n'
            '    with app.app_context():\n'
            '        _db.create_all()\n'
            '        yield app\n'
            '        _db.drop_all()\n'
            '\n'
            '\n'
            '@pytest.fixture\n'
            'def client(app):\n'
            '    return app.test_client()\n'
        ),
        "tests/test_products.py": (
            'from app.models import Product\n'
            'from app.db import db\n'
            '\n'
            '\n'
            'def test_list_products(client):\n'
            '    db.session.add(Product(name="Widget", category="tools", price=9.99))\n'
            '    db.session.commit()\n'
            '    response = client.get("/products/")\n'
            '    assert response.status_code == 200\n'
            '    data = response.get_json()\n'
            '    assert len(data) == 1\n'
            '    assert data[0]["name"] == "Widget"\n'
            '\n'
            '\n'
            'def test_get_product_not_found(client):\n'
            '    response = client.get("/products/999")\n'
            '    assert response.status_code == 404\n'
        ),
    },
    "checks": {
        "must_modify": ["app/routes/products.py"],
        "should_not_create": [
            "app/routes/products.py",
            "app/models.py",
            "app/db.py",
        ],
        "expect_files_matching": [],
        "test_framework": "pytest",
    },
}

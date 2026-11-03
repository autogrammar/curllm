"""Flask application setup for curllm server"""

import logging

from flask import Flask, jsonify
from flask_cors import CORS

from curllm_server.routes.health import health_bp
from curllm_server.routes.execute import execute_bp
from curllm_server.routes.models import models_bp
from curllm_server.routes.screenshot import screenshot_bp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)
CORS(app)

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not Found", "status": "error", "code": 404}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal Server Error", "status": "error", "code": 500}), 500

# Register blueprints
app.register_blueprint(health_bp)
app.register_blueprint(execute_bp)
app.register_blueprint(models_bp)
app.register_blueprint(screenshot_bp)

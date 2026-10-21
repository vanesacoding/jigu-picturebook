"""叽咕插画 V0 —— 启动入口。

  python run.py
  # 打开 http://127.0.0.1:7860

私用约束：默认只监听 127.0.0.1，不做公网部署；API Key 只从服务端环境变量读取。
"""

from __future__ import annotations

import pathlib
import sys

from flask import Flask, jsonify, send_from_directory

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from server import api, config, db  # noqa: E402


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(config.WEB_DIR), static_url_path="/assets")
    # 单张照片按 10MB 上限，6 张留足余量
    app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024
    app.register_blueprint(api.api, url_prefix="/api")
    db.init_db()

    @app.get("/")
    def index():
        return send_from_directory(config.WEB_DIR, "index.html")

    @app.get("/<path:name>")
    def static_any(name: str):
        target = config.WEB_DIR / pathlib.Path(name).name
        if target.is_file():
            return send_from_directory(config.WEB_DIR, target.name)
        return send_from_directory(config.WEB_DIR, "index.html")

    @app.errorhandler(413)
    def too_large(_exc):
        return jsonify({"ok": False, "error": "照片太大了，请压缩后重试（单张建议 < 10MB）"}), 413

    @app.errorhandler(500)
    def server_error(exc):
        app.logger.exception("server error: %s", exc)
        return jsonify({"ok": False, "error": "服务端出错了，请查看终端日志"}), 500

    return app


app = create_app()

if __name__ == "__main__":
    status = api.worker.model_status()
    print("=" * 58)
    print("叽咕插画 V0")
    print(f"  地址     http://{config.HOST}:{config.PORT}")
    print(f"  数据目录 {config.DATA_DIR}")
    print(f"  模型     {status.get('model') or config.DEFAULT_MODEL}"
          f"{'' if status.get('ok') else '（不可用：' + str(status.get('error'))[:60] + '）'}")
    print(f"  预算上限 ¥{config.APP_BUDGET_CNY:.0f}（已用 ¥{db.spent_total():.2f}）")
    print("  提示     手机访问请用同一局域网 IP，或将 7860 端口转发到手机")
    print("=" * 58)
    app.run(host=config.HOST, port=config.PORT, debug=False, threaded=True)
